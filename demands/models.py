import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RequirementQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(models.Q(creator=user) | models.Q(assignee=user))


class Requirement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        IN_PROGRESS = "in_progress", "进行中"
        IN_REVIEW = "in_review", "待验收"
        COMPLETED = "completed", "已完成"

    title = models.CharField("标题", max_length=200)
    description = models.TextField("需求说明")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_requirements",
        verbose_name="提出者",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_requirements",
        verbose_name="负责人",
    )
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    lock_version = models.PositiveIntegerField("数据版本", default=1)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = RequirementQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "需求"
        verbose_name_plural = "需求"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(creator=models.F("assignee")),
                name="requirement_creator_differs_from_assignee",
            )
        ]

    def clean(self):
        super().clean()
        if self.creator_id and self.creator_id == self.assignee_id:
            raise ValidationError({"assignee": "负责人不能与提出者相同。"})

    def __str__(self):
        return self.title


class AcceptanceCriterion(models.Model):
    requirement = models.ForeignKey(
        Requirement,
        on_delete=models.CASCADE,
        related_name="criteria",
        verbose_name="所属需求",
    )
    content = models.CharField("验收条件", max_length=500)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "验收条件"
        verbose_name_plural = "验收条件"
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "sort_order"],
                name="unique_criterion_order_per_requirement",
            )
        ]

    def __str__(self):
        return self.content


class Submission(models.Model):
    """一次不可变的成果提交。V1、V2 分别保存为独立记录。"""

    requirement = models.ForeignKey(
        Requirement,
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name="所属需求",
    )
    version = models.PositiveIntegerField("提交版本")
    result_url = models.URLField("成果链接", max_length=1000)
    description = models.TextField("完成说明")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requirement_submissions",
        verbose_name="提交人",
    )
    idempotency_key = models.UUIDField(
        "幂等请求标识",
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )
    created_at = models.DateTimeField("提交时间", auto_now_add=True)

    class Meta:
        ordering = ["requirement_id", "version"]
        verbose_name = "成果提交"
        verbose_name_plural = "成果提交"
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "version"],
                name="unique_submission_version_per_requirement",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="submission_version_gte_one",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.requirement_id
            and self.submitted_by_id
            and self.submitted_by_id != self.requirement.assignee_id
        ):
            raise ValidationError({"submitted_by": "只有需求负责人可以提交成果。"})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("历史提交不可修改，请创建新的提交版本。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("历史提交不可删除。")

    def __str__(self):
        return f"{self.requirement} · V{self.version}"


class Review(models.Model):
    """一次提交对应的一次不可变审核。"""

    class Decision(models.TextChoices):
        RETURNED = "returned", "退回"
        APPROVED = "approved", "通过"

    submission = models.OneToOneField(
        Submission,
        on_delete=models.PROTECT,
        related_name="review",
        verbose_name="被审核提交",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requirement_reviews",
        verbose_name="审核人",
    )
    decision = models.CharField("审核结论", max_length=20, choices=Decision.choices)
    return_reason = models.TextField("退回总说明", blank=True)
    idempotency_key = models.UUIDField(
        "幂等请求标识",
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )
    created_at = models.DateTimeField("审核时间", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "提交审核"
        verbose_name_plural = "提交审核"

    def clean(self):
        super().clean()
        if (
            self.submission_id
            and self.reviewer_id
            and self.reviewer_id != self.submission.requirement.creator_id
        ):
            raise ValidationError({"reviewer": "只有需求提出者可以验收。"})
        if self.decision == self.Decision.RETURNED and not self.return_reason.strip():
            raise ValidationError({"return_reason": "退回时必须填写具体修改原因。"})
        if self.decision == self.Decision.APPROVED and self.return_reason.strip():
            raise ValidationError({"return_reason": "通过时不应填写退回原因。"})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("历史审核不可修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("历史审核不可删除。")

    def __str__(self):
        return f"{self.submission} · {self.get_decision_display()}"


class ReviewResult(models.Model):
    """审核中某一条验收条件的不可变检查结果。"""

    review = models.ForeignKey(
        Review,
        on_delete=models.PROTECT,
        related_name="results",
        verbose_name="所属审核",
    )
    criterion = models.ForeignKey(
        AcceptanceCriterion,
        on_delete=models.PROTECT,
        related_name="review_results",
        verbose_name="验收条件",
    )
    passed = models.BooleanField("是否通过")
    comment = models.TextField("检查说明", blank=True)

    class Meta:
        ordering = ["criterion__sort_order", "criterion_id"]
        verbose_name = "逐项验收结果"
        verbose_name_plural = "逐项验收结果"
        constraints = [
            models.UniqueConstraint(
                fields=["review", "criterion"],
                name="unique_result_per_review_criterion",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.review_id
            and self.criterion_id
            and self.review.submission.requirement_id != self.criterion.requirement_id
        ):
            raise ValidationError({"criterion": "验收条件不属于该提交对应的需求。"})
        if self.passed is False and not self.comment.strip():
            raise ValidationError({"comment": "未通过项必须填写具体修改说明。"})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("历史逐项验收结果不可修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("历史逐项验收结果不可删除。")

    def __str__(self):
        result = "通过" if self.passed else "未通过"
        return f"{self.criterion} · {result}"


class OperationLog(models.Model):
    requirement = models.ForeignKey(
        Requirement,
        on_delete=models.PROTECT,
        related_name="logs",
        verbose_name="所属需求",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requirement_logs",
        verbose_name="操作人",
    )
    submission = models.ForeignKey(
        Submission,
        on_delete=models.PROTECT,
        related_name="operation_logs",
        verbose_name="相关提交",
        blank=True,
        null=True,
    )
    action = models.CharField("操作", max_length=50)
    from_status = models.CharField("原状态", max_length=20, blank=True)
    to_status = models.CharField("新状态", max_length=20, blank=True)
    description = models.TextField("操作说明", blank=True)
    metadata = models.JSONField("附加快照", default=dict, blank=True)
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "操作历史"
        verbose_name_plural = "操作历史"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("操作历史不可修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("操作历史不可删除。")

    def __str__(self):
        return f"{self.actor.username} - {self.action}"
