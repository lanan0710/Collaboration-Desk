from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RegistrationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待审批"
        APPROVED = "approved", "已批准"
        REJECTED = "rejected", "已拒绝"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="registration_request",
        verbose_name="申请用户",
    )
    requested_admin = models.BooleanField("申请业务管理员", default=False)
    admin_request_reason = models.TextField("申请理由", blank=True)
    status = models.CharField(
        "审批状态",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    approved_as_admin = models.BooleanField("批准为业务管理员", default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_registration_requests",
        verbose_name="审批人",
    )
    review_note = models.TextField("审批备注", blank=True)
    created_at = models.DateTimeField("申请时间", auto_now_add=True)
    reviewed_at = models.DateTimeField("审批时间", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "注册申请"
        verbose_name_plural = "注册申请"
        permissions = [
            ("approve_registration_requests", "可以审批普通成员注册申请"),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.requested_admin and not self.admin_request_reason.strip():
            raise ValidationError({"admin_request_reason": "申请业务管理员时必须填写理由。"})
        if not self.requested_admin:
            self.admin_request_reason = ""
        if self.approved_as_admin and not self.requested_admin:
            raise ValidationError({"approved_as_admin": "用户未申请业务管理员权限。"})
