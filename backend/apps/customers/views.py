from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit import services as audit
from apps.organizations.permissions import MethodPermissions
from apps.tickets.models import ACTIVE_STATUSES

from .models import Customer, CustomerContact
from .serializers import CustomerContactSerializer, CustomerSerializer


class CustomerFilter(filters.FilterSet):
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Customer
        fields = ("type", "tier", "archived")


@extend_schema(tags=["customers"])
class CustomerViewSet(viewsets.ModelViewSet):
    """Customers of the current organization. DELETE archives (customers with history are never deleted)."""

    permission_classes = [MethodPermissions]
    method_permissions = {
        "GET": ["customers.view"],
        "POST": ["customers.manage"],
        "PATCH": ["customers.manage"],
        "PUT": ["customers.manage"],
        "DELETE": ["customers.manage"],
    }
    serializer_class = CustomerSerializer
    filterset_class = CustomerFilter
    search_fields = ("name", "email", "phone", "city", "contacts__name", "contacts__email")
    ordering_fields = ("name", "created_at", "open_ticket_count")
    ordering = ("name",)

    def _annotated_queryset(self):
        return (
            Customer.objects.filter(organization=self.request.organization)
            .annotate(
                open_ticket_count=Count(
                    "tickets",
                    filter=Q(tickets__status__in=ACTIVE_STATUSES, tickets__archived_at__isnull=True),
                    distinct=True,
                ),
                asset_count=Count("assets", distinct=True),
            )
            .prefetch_related(Prefetch("contacts", queryset=CustomerContact.objects.filter(is_primary=True)))
        )

    def get_queryset(self):
        qs = self._annotated_queryset()
        if self.action == "list" and "archived" not in self.request.query_params:
            qs = qs.filter(archived_at__isnull=True)
        return qs.distinct()

    def _respond_with_counts(self, response):
        """Writes return the saved object re-read with its computed counts."""
        instance = self._annotated_queryset().get(pk=response.data["id"])
        response.data = self.get_serializer(instance).data
        return response

    def create(self, request, *args, **kwargs):
        return self._respond_with_counts(super().create(request, *args, **kwargs))

    def update(self, request, *args, **kwargs):
        return self._respond_with_counts(super().update(request, *args, **kwargs))

    def perform_create(self, serializer):
        customer = serializer.save(organization=self.request.organization)
        audit.record("customer.created", request=self.request, target=customer)

    def perform_update(self, serializer):
        customer = serializer.save()
        audit.record(
            "customer.updated",
            request=self.request,
            target=customer,
            changes={k: str(v) for k, v in serializer.validated_data.items()},
        )

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.archived_at = timezone.now()
        customer.save(update_fields=["archived_at", "updated_at"])
        audit.record("customer.archived", request=request, target=customer)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=CustomerSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        customer = self.get_object()
        customer.archived_at = None
        customer.save(update_fields=["archived_at", "updated_at"])
        audit.record("customer.restored", request=request, target=customer)
        return Response(self.get_serializer(self.get_queryset().get(pk=customer.pk)).data)


@extend_schema(tags=["customers"])
class CustomerContactViewSet(viewsets.ModelViewSet):
    """Contacts nested under /customers/{customer_id}/contacts/."""

    permission_classes = [MethodPermissions]
    method_permissions = CustomerViewSet.method_permissions
    serializer_class = CustomerContactSerializer
    pagination_class = None

    def get_customer(self) -> Customer:
        return get_object_or_404(Customer, pk=self.kwargs["customer_pk"], organization=self.request.organization)

    def get_queryset(self):
        return CustomerContact.objects.filter(customer=self.get_customer())

    @transaction.atomic
    def _save(self, serializer, **extra):
        if serializer.validated_data.get("is_primary"):
            # Exactly one primary contact per customer.
            CustomerContact.objects.filter(customer=self.get_customer(), is_primary=True).update(is_primary=False)
        return serializer.save(**extra)

    def perform_create(self, serializer):
        contact = self._save(serializer, customer=self.get_customer())
        audit.record("customer_contact.created", request=self.request, target=contact)

    def perform_update(self, serializer):
        contact = self._save(serializer)
        audit.record("customer_contact.updated", request=self.request, target=contact)

    def perform_destroy(self, instance):
        audit.record("customer_contact.deleted", request=self.request, target=instance, changes={"name": instance.name})
        instance.delete()
