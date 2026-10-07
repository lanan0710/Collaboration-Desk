from django.contrib import admin

from .models import (
    AcceptanceCriterion,
    OperationLog,
    Requirement,
    Review,
    ReviewResult,
    Submission,
    SubmissionAttachment,
)


class AcceptanceCriterionInline(admin.TabularInline):
    model = AcceptanceCriterion
    extra = 0


@admin.register(Requirement)
class RequirementAdmin(admin.ModelAdmin):
    list_display = ("title", "creator", "assignee", "status", "lock_version", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "description", "creator__username", "assignee__username")
    inlines = (AcceptanceCriterionInline,)


class ImmutableHistoryAdmin(admin.ModelAdmin):
    """历史数据在后台仅用于查看，避免管理员意外覆盖审计链。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Submission)
class SubmissionAdmin(ImmutableHistoryAdmin):
    list_display = ("requirement", "version", "submitted_by", "created_at")
    list_filter = ("created_at",)


@admin.register(SubmissionAttachment)
class SubmissionAttachmentAdmin(ImmutableHistoryAdmin):
    list_display = ("submission", "original_name", "size", "created_at")


@admin.register(Review)
class ReviewAdmin(ImmutableHistoryAdmin):
    list_display = ("submission", "reviewer", "decision", "created_at")
    list_filter = ("decision", "created_at")


@admin.register(ReviewResult)
class ReviewResultAdmin(ImmutableHistoryAdmin):
    list_display = ("review", "criterion", "passed")
    list_filter = ("passed",)


@admin.register(OperationLog)
class OperationLogAdmin(ImmutableHistoryAdmin):
    list_display = ("requirement", "actor", "action", "from_status", "to_status", "created_at")
    list_filter = ("action", "from_status", "to_status")
