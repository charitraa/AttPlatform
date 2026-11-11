from rest_framework.permissions import BasePermission

from .tenancy import attach_tenant


class IsOrganizationMember(BasePermission):
    """Authenticated user with an active membership; attaches the tenant context."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        attach_tenant(request)  # raises 403 if the user has no active membership
        return True


def HasPermission(*codes: str, any_of: bool = False) -> type[BasePermission]:  # noqa: N802 - reads like a class
    """
    Permission class factory: `permission_classes = [HasPermission("users.manage")]`.
    Requires all codes by default, or any of them with `any_of=True`.
    """

    class _HasPermission(IsOrganizationMember):
        required = frozenset(codes)

        def has_permission(self, request, view) -> bool:
            if not super().has_permission(request, view):
                return False
            granted = request.tenant.permissions
            return bool(self.required & granted) if any_of else self.required <= granted

    _HasPermission.__name__ = f"HasPermission({', '.join(codes)})"
    return _HasPermission


class MethodPermissions(IsOrganizationMember):
    """
    Per-HTTP-method permission codes declared on the view:

        method_permissions = {"GET": ["users.view"], "PATCH": ["users.manage"]}

    Methods not listed are denied (secure by default).
    """

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        mapping = getattr(view, "method_permissions", {})
        method = "GET" if request.method in ("HEAD", "OPTIONS") else request.method
        if method not in mapping:
            return False
        return set(mapping[method]) <= request.tenant.permissions
