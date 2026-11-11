from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CustomerContactViewSet, CustomerViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")

contact_list = CustomerContactViewSet.as_view({"get": "list", "post": "create"})
contact_detail = CustomerContactViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})

urlpatterns = [
    *router.urls,
    path("customers/<uuid:customer_pk>/contacts/", contact_list, name="customer-contact-list"),
    path("customers/<uuid:customer_pk>/contacts/<uuid:pk>/", contact_detail, name="customer-contact-detail"),
]
