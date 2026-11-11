from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.register("users", views.MemberViewSet, basename="member")
router.register("invitations", views.InvitationViewSet, basename="invitation")
router.register("roles", views.RoleViewSet, basename="role")
router.register("audit-logs", views.AuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("organization/", views.OrganizationView.as_view(), name="organization"),
    *router.urls,
]
