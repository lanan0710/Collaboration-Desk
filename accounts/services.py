from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import RegistrationRequest


BUSINESS_ADMIN_GROUP = "业务管理员"
User = get_user_model()


def _business_admin_group():
    group, _ = Group.objects.get_or_create(name=BUSINESS_ADMIN_GROUP)
    permissions = Permission.objects.filter(
        content_type__app_label="accounts",
        codename__in=["view_registrationrequest", "approve_registration_requests"],
    )
    group.permissions.add(*permissions)
    return group


def can_approve_members(actor):
    return actor.is_authenticated and (
        actor.is_superuser
        or actor.has_perm("accounts.approve_registration_requests")
    )


@transaction.atomic
def create_registration(form):
    user = form.save(commit=False)
    user.email = form.cleaned_data["email"]
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.save()

    application = RegistrationRequest(
        user=user,
        requested_admin=form.cleaned_data.get("requested_admin", False),
        admin_request_reason=form.cleaned_data.get("admin_request_reason", "").strip(),
    )
    application.full_clean()
    application.save()
    return application


def _locked_application(application_id):
    return (
        RegistrationRequest.objects.select_for_update()
        .select_related("user")
        .get(pk=application_id)
    )


def _ensure_pending(application):
    if application.status != RegistrationRequest.Status.PENDING:
        raise ValidationError("该注册申请已经处理，不能重复审批。")


@transaction.atomic
def approve_registration(application_id, actor, *, as_admin=False, review_note=""):
    if not can_approve_members(actor):
        raise PermissionDenied("你没有审批注册申请的权限。")
    if as_admin and not actor.is_superuser:
        raise PermissionDenied("只有超级管理员可以批准业务管理员权限。")

    application = _locked_application(application_id)
    _ensure_pending(application)
    if as_admin and not application.requested_admin:
        raise ValidationError("该用户没有申请业务管理员权限。")

    user = User.objects.select_for_update().get(pk=application.user_id)
    if user.is_superuser:
        raise ValidationError("网页注册用户不能成为超级管理员。")

    user.is_active = True
    user.is_staff = as_admin
    user.is_superuser = False
    user.save(update_fields=["is_active", "is_staff", "is_superuser"])

    group = _business_admin_group()
    if as_admin:
        user.groups.add(group)
    else:
        user.groups.remove(group)

    application.status = RegistrationRequest.Status.APPROVED
    application.approved_as_admin = as_admin
    application.reviewed_by = actor
    application.review_note = review_note.strip()
    application.reviewed_at = timezone.now()
    application.full_clean()
    application.save(
        update_fields=[
            "status",
            "approved_as_admin",
            "reviewed_by",
            "review_note",
            "reviewed_at",
        ]
    )
    return application


@transaction.atomic
def reject_registration(application_id, actor, *, review_note=""):
    if not can_approve_members(actor):
        raise PermissionDenied("你没有审批注册申请的权限。")

    application = _locked_application(application_id)
    _ensure_pending(application)
    user = User.objects.select_for_update().get(pk=application.user_id)
    if user.is_superuser:
        raise ValidationError("不能通过注册审批修改超级管理员。")

    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["is_active", "is_staff", "is_superuser"])
    user.groups.remove(_business_admin_group())

    application.status = RegistrationRequest.Status.REJECTED
    application.approved_as_admin = False
    application.reviewed_by = actor
    application.review_note = review_note.strip()
    application.reviewed_at = timezone.now()
    application.save(
        update_fields=[
            "status",
            "approved_as_admin",
            "reviewed_by",
            "review_note",
            "reviewed_at",
        ]
    )
    return application
