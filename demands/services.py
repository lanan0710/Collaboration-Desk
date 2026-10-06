from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from .models import (
    AcceptanceCriterion,
    OperationLog,
    Requirement,
    Review,
    ReviewResult,
    Submission,
)


class StaleRequirementError(ValidationError):
    """页面中的版本已经落后于数据库版本。"""


def _clean_criterion_texts(criterion_texts):
    cleaned = [str(item).strip() for item in criterion_texts if str(item).strip()]
    if not cleaned:
        raise ValidationError("至少需要一条验收条件。")
    return cleaned


def _lock_requirement(requirement_id):
    try:
        return Requirement.objects.select_for_update().get(pk=requirement_id)
    except Requirement.DoesNotExist as exc:
        raise ValidationError("需求不存在。") from exc


def _check_version(requirement, expected_lock_version):
    if requirement.lock_version != expected_lock_version:
        raise StaleRequirementError("页面数据已过期，请刷新后重试。")


def _advance(requirement, target_status):
    requirement.status = target_status
    requirement.lock_version += 1
    requirement.save(update_fields=["status", "lock_version", "updated_at"])


@transaction.atomic
def create_requirement(*, actor, assignee, title, description, criterion_texts):
    criteria = _clean_criterion_texts(criterion_texts)
    requirement = Requirement(
        title=title.strip(),
        description=description.strip(),
        creator=actor,
        assignee=assignee,
    )
    requirement.full_clean()
    requirement.save()

    for sort_order, content in enumerate(criteria, start=1):
        criterion = AcceptanceCriterion(
            requirement=requirement,
            content=content,
            sort_order=sort_order,
        )
        criterion.full_clean()
        criterion.save()

    OperationLog.objects.create(
        requirement=requirement,
        actor=actor,
        action="create",
        to_status=Requirement.Status.PENDING,
        description="创建需求并指定负责人。",
        metadata={"criterion_count": len(criteria)},
    )
    return requirement


@transaction.atomic
def edit_requirement(
    *,
    requirement_id,
    actor,
    expected_lock_version,
    title,
    description,
    criterion_texts,
):
    criteria = _clean_criterion_texts(criterion_texts)
    requirement = _lock_requirement(requirement_id)
    _check_version(requirement, expected_lock_version)

    if requirement.creator_id != actor.id:
        raise PermissionDenied("只有需求提出者可以编辑需求。")
    if requirement.status != Requirement.Status.PENDING:
        raise ValidationError("需求开始处理后，正文和验收条件将被冻结。")

    old_snapshot = {
        "title": requirement.title,
        "description": requirement.description,
        "criteria": list(requirement.criteria.values_list("content", flat=True)),
    }
    requirement.title = title.strip()
    requirement.description = description.strip()
    requirement.lock_version += 1
    requirement.full_clean()
    requirement.save(
        update_fields=["title", "description", "lock_version", "updated_at"]
    )

    requirement.criteria.all().delete()
    for sort_order, content in enumerate(criteria, start=1):
        criterion = AcceptanceCriterion(
            requirement=requirement,
            content=content,
            sort_order=sort_order,
        )
        criterion.full_clean()
        criterion.save()

    OperationLog.objects.create(
        requirement=requirement,
        actor=actor,
        action="edit",
        from_status=Requirement.Status.PENDING,
        to_status=Requirement.Status.PENDING,
        description="修改需求正文或验收条件。",
        metadata={"before": old_snapshot},
    )
    return requirement


@transaction.atomic
def start_requirement(*, requirement_id, actor, expected_lock_version):
    requirement = _lock_requirement(requirement_id)
    _check_version(requirement, expected_lock_version)

    if requirement.assignee_id != actor.id:
        raise PermissionDenied("只有需求负责人可以开始处理。")
    if requirement.status != Requirement.Status.PENDING:
        raise ValidationError("只有待处理需求可以开始。")

    _advance(requirement, Requirement.Status.IN_PROGRESS)
    OperationLog.objects.create(
        requirement=requirement,
        actor=actor,
        action="start",
        from_status=Requirement.Status.PENDING,
        to_status=Requirement.Status.IN_PROGRESS,
        description="负责人开始处理，需求正文和验收条件已冻结。",
    )
    return requirement


@transaction.atomic
def submit_result(
    *,
    requirement_id,
    actor,
    expected_lock_version,
    result_url,
    description,
    idempotency_key,
):
    requirement = _lock_requirement(requirement_id)

    existing = Submission.objects.filter(
        requirement=requirement,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        return existing

    _check_version(requirement, expected_lock_version)
    if requirement.assignee_id != actor.id:
        raise PermissionDenied("只有需求负责人可以提交成果。")
    if requirement.status != Requirement.Status.IN_PROGRESS:
        raise ValidationError("只有进行中的需求可以提交成果。")

    latest_version = (
        requirement.submissions.aggregate(value=Max("version"))["value"] or 0
    )
    submission = Submission(
        requirement=requirement,
        version=latest_version + 1,
        result_url=result_url.strip(),
        description=description.strip(),
        submitted_by=actor,
        idempotency_key=idempotency_key,
    )
    submission.full_clean()
    submission.save()

    _advance(requirement, Requirement.Status.IN_REVIEW)
    OperationLog.objects.create(
        requirement=requirement,
        actor=actor,
        submission=submission,
        action="submit",
        from_status=Requirement.Status.IN_PROGRESS,
        to_status=Requirement.Status.IN_REVIEW,
        description=f"提交成果 V{submission.version}。",
    )
    return submission


def _normalize_results(requirement, results):
    criteria = list(requirement.criteria.all())
    expected_ids = {criterion.id for criterion in criteria}
    supplied_ids = {int(key) for key in results}
    if supplied_ids != expected_ids:
        raise ValidationError("必须重新检查并提交全部验收条件。")

    normalized = []
    for criterion in criteria:
        raw = results.get(criterion.id, results.get(str(criterion.id)))
        passed = raw.get("passed")
        comment = str(raw.get("comment", "")).strip()
        if not isinstance(passed, bool):
            raise ValidationError("每条验收条件必须明确选择通过或未通过。")
        if not passed and not comment:
            raise ValidationError("每个未通过项都必须填写具体修改说明。")
        normalized.append((criterion, passed, comment))
    return normalized


@transaction.atomic
def review_submission(
    *,
    requirement_id,
    submission_id,
    actor,
    expected_lock_version,
    decision,
    results,
    idempotency_key,
    return_reason="",
):
    requirement = _lock_requirement(requirement_id)

    existing = Review.objects.select_related("submission").filter(
        idempotency_key=idempotency_key
    ).first()
    if existing:
        if (
            existing.submission.requirement_id != requirement.id
            or existing.reviewer_id != actor.id
        ):
            raise ValidationError("幂等请求标识与原审核请求不匹配。")
        return existing

    _check_version(requirement, expected_lock_version)
    if requirement.creator_id != actor.id:
        raise PermissionDenied("只有需求提出者可以验收。")
    if requirement.status != Requirement.Status.IN_REVIEW:
        raise ValidationError("只有待验收需求可以审核。")

    current_submission = requirement.submissions.order_by("-version").first()
    if current_submission is None or current_submission.id != submission_id:
        raise StaleRequirementError("该提交已不是当前待验收版本，请刷新后重试。")

    normalized = _normalize_results(requirement, results)
    all_passed = all(passed for _, passed, _ in normalized)
    any_failed = any(not passed for _, passed, _ in normalized)
    return_reason = return_reason.strip()

    if decision == Review.Decision.APPROVED:
        if not all_passed:
            raise ValidationError("仍有未通过项，不能确认完成。")
        target_status = Requirement.Status.COMPLETED
    elif decision == Review.Decision.RETURNED:
        if not any_failed:
            raise ValidationError("退回时至少需要一个未通过项。")
        if not return_reason:
            raise ValidationError("退回时必须填写具体修改原因。")
        target_status = Requirement.Status.IN_PROGRESS
    else:
        raise ValidationError("未知的审核结论。")

    review = Review(
        submission=current_submission,
        reviewer=actor,
        decision=decision,
        return_reason=return_reason,
        idempotency_key=idempotency_key,
    )
    review.full_clean()
    review.save()

    for criterion, passed, comment in normalized:
        result = ReviewResult(
            review=review,
            criterion=criterion,
            passed=passed,
            comment=comment,
        )
        result.full_clean()
        result.save()

    _advance(requirement, target_status)
    action = "approve" if decision == Review.Decision.APPROVED else "return"
    OperationLog.objects.create(
        requirement=requirement,
        actor=actor,
        submission=current_submission,
        action=action,
        from_status=Requirement.Status.IN_REVIEW,
        to_status=target_status,
        description=(
            f"验收通过 V{current_submission.version}。"
            if decision == Review.Decision.APPROVED
            else f"退回 V{current_submission.version}：{return_reason}"
        ),
        metadata={
            "results": [
                {
                    "criterion_id": criterion.id,
                    "passed": passed,
                    "comment": comment,
                }
                for criterion, passed, comment in normalized
            ]
        },
    )
    return review
