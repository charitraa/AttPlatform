from django.contrib import admin

from .models import Invitation, Membership, Organization, Permission, Role, RolePermission


class MembershipInline(admin.TabularInline):
    model = Membership
    fk_name = "organization"
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "role", "is_active", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (MembershipInline,)


class RolePermissionInline(admin.TabularInline):
    """Read-only: system role permissions are defined in catalog.py and synced on migrate."""

    model = RolePermission
    extra = 0
    can_delete = False
    readonly_fields = ("permission",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "rank", "organization", "is_system")
    readonly_fields = ("code", "rank", "is_system")
    inlines = (RolePermissionInline,)


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "description")
    search_fields = ("code",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "organization__name")
    autocomplete_fields = ("user", "organization")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "role", "status", "expires_at", "created_at")
    search_fields = ("email",)
    exclude = ("token_hash",)
    readonly_fields = ("accepted_at", "revoked_at")
