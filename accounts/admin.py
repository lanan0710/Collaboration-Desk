from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from .models import RegistrationRequest
from .services import approve_registration, can_approve_members, reject_registration


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "requested_admin",
        "status",
        "approved_as_admin",
        "created_at",
        "reviewed_by",
    )
    list_filter = ("status", "requested_admin", "approved_as_admin")
    search_fields = ("user__username", "user__email", "admin_request_reason")
    readonly_fields = (
        "user",
        "requested_admin",
        "admin_request_reason",
        "status",
        "approved_as_admin",
        "reviewed_by",
        "review_note",
        "created_at",
        "reviewed_at",
    )
    actions = ("approve_as_member", "approve_as_admin", "reject_requests")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_approve_permission(self, request):
        return can_approve_members(request.user)

    def has_superuser_permission(self, request):
        return request.user.is_superuser

    def _run_action(self, request, queryset, callback, success_message):
        succeeded = 0
        for application in queryset:
            try:
                callback(application.pk)
            except (PermissionDenied, ValidationError) as exc:
                self.message_user(
                    request,
                    f"{application.user.username}：{'; '.join(exc.messages)}",
                    level=messages.ERROR,
                )
            else:
                succeeded += 1
        if succeeded:
            self.message_user(request, success_message.format(count=succeeded))

    @admin.action(description="批准为普通成员", permissions=["approve"])
    def approve_as_member(self, request, queryset):
        self._run_action(
            request,
            queryset,
            lambda pk: approve_registration(pk, request.user),
            "已批准 {count} 个普通成员账号。",
        )

    @admin.action(description="批准为业务管理员（仅超级管理员）", permissions=["superuser"])
    def approve_as_admin(self, request, queryset):
        self._run_action(
            request,
            queryset,
            lambda pk: approve_registration(pk, request.user, as_admin=True),
            "已批准 {count} 个业务管理员账号。",
        )

    @admin.action(description="拒绝注册申请", permissions=["approve"])
    def reject_requests(self, request, queryset):
        self._run_action(
            request,
            queryset,
            lambda pk: reject_registration(pk, request.user),
            "已拒绝 {count} 个注册申请。",
        )
