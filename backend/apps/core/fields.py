from rest_framework import serializers


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """
    A PK field whose choices are limited to the request's organization, so a client
    can never point at another tenant's object (it gets "does not exist" instead).

        customer = OrgScopedPrimaryKeyRelatedField(queryset=Customer.objects.all())

    By default filters `organization=<org>`; pass `org_path="customer__organization"`
    for models that reach the organization through a relation.
    """

    def __init__(self, *, org_path: str = "organization", **kwargs):
        self.org_path = org_path
        super().__init__(**kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        organization = getattr(request, "organization", None)
        qs = super().get_queryset()
        if organization is None:
            return qs.none()
        return qs.filter(**{self.org_path: organization})
