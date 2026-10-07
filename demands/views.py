import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    CriterionFormSet,
    RequirementCreateForm,
    ReviewCriterionFormSet,
    ReviewDecisionForm,
    StartRequirementForm,
    SubmissionForm,
)
from .models import OperationLog, Requirement, Review, SubmissionAttachment
from .presentation import decorate_requirement, user_action_hint
from .services import (
    create_requirement,
    review_submission,
    start_requirement,
    submit_result,
)


def _requirement_queryset(user):
    return (
        Requirement.objects.visible_to(user)
        .select_related("creator", "assignee")
        .prefetch_related(
            "criteria",
            "submissions__submitted_by",
            "submissions__attachments",
            "submissions__review__reviewer",
            "submissions__review__results__criterion",
            Prefetch(
                "logs",
                queryset=OperationLog.objects.select_related("actor", "submission"),
            ),
        )
    )


def _get_requirement(user, pk):
    return get_object_or_404(_requirement_queryset(user), pk=pk)


def _review_initial(requirement):
    return [
        {"criterion_id": criterion.pk, "criterion_text": criterion.content}
        for criterion in requirement.criteria.all()
    ]


def _detail_context(
    requirement,
    user,
    *,
    start_form=None,
    submission_form=None,
    review_form=None,
    review_formset=None,
):
    decorate_requirement(requirement)
    can_start = (
        requirement.assignee_id == user.id
        and requirement.status == Requirement.Status.PENDING
    )
    can_submit = (
        requirement.assignee_id == user.id
        and requirement.status == Requirement.Status.IN_PROGRESS
    )
    can_review = (
        requirement.creator_id == user.id
        and requirement.status == Requirement.Status.IN_REVIEW
        and requirement.latest_submission_for_ui is not None
    )

    if can_start and start_form is None:
        start_form = StartRequirementForm(
            initial={"lock_version": requirement.lock_version}
        )
    if can_submit and submission_form is None:
        submission_form = SubmissionForm(
            initial={
                "lock_version": requirement.lock_version,
                "idempotency_key": uuid.uuid4(),
            }
        )
    if can_review:
        latest_submission = requirement.latest_submission_for_ui
        criterion_initial = _review_initial(requirement)
        if review_form is None:
            review_form = ReviewDecisionForm(
                initial={
                    "lock_version": requirement.lock_version,
                    "submission_id": latest_submission.pk,
                    "idempotency_key": uuid.uuid4(),
                }
            )
        if review_formset is None:
            review_formset = ReviewCriterionFormSet(
                initial=criterion_initial,
                prefix="review_items",
            )

    return {
        "requirement": requirement,
        "action_hint": user_action_hint(requirement, user),
        "can_start": can_start,
        "can_submit": can_submit,
        "can_review": can_review,
        "start_form": start_form,
        "submission_form": submission_form,
        "review_form": review_form,
        "review_formset": review_formset,
    }


# 只有已登录成功的用户才执行 home 函数，否则跳转到登录页面。
@login_required
def home(request):
    if request.method == "POST":
        form = RequirementCreateForm(request.POST, actor=request.user)
        criterion_formset = CriterionFormSet(request.POST, prefix="criteria")
        if form.is_valid() and criterion_formset.is_valid():
            criterion_texts = [
                criterion_form.cleaned_data["content"]
                for criterion_form in criterion_formset
                if criterion_form.cleaned_data
            ]
            try:
                requirement = create_requirement(
                    actor=request.user,
                    assignee=form.cleaned_data["assignee"],
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    criterion_texts=criterion_texts,
                )
            except ValidationError as exc:
                form.add_error(None, "；".join(exc.messages))
            else:
                messages.success(request, f"需求“{requirement.title}”已创建。")
                return redirect("demands:home")
    else:
        form = RequirementCreateForm(actor=request.user)
        criterion_formset = CriterionFormSet(prefix="criteria")

    visible_requirements = list(
        Requirement.objects.visible_to(request.user)
        .select_related("creator", "assignee")
        .prefetch_related("criteria", "submissions__review")
    )
    for requirement in visible_requirements:
        decorate_requirement(requirement)

    context = {
        "form": form,
        "criterion_formset": criterion_formset,
        "created_requirements": [
            requirement
            for requirement in visible_requirements
            if requirement.creator_id == request.user.id
        ],
        "assigned_requirements": [
            requirement
            for requirement in visible_requirements
            if requirement.assignee_id == request.user.id
        ],
    }
    return render(request, "demands/home.html", context)


@login_required
def requirement_detail(request, pk):
    requirement = _get_requirement(request.user, pk)
    return render(
        request,
        "demands/requirement_detail.html",
        _detail_context(requirement, request.user),
    )


@login_required
@require_POST
def requirement_start(request, pk):
    requirement = _get_requirement(request.user, pk)
    if requirement.assignee_id != request.user.id:
        raise PermissionDenied("只有需求负责人可以开始处理。")

    form = StartRequirementForm(request.POST)
    if form.is_valid():
        try:
            start_requirement(
                requirement_id=requirement.pk,
                actor=request.user,
                expected_lock_version=form.cleaned_data["lock_version"],
            )
        except PermissionDenied:
            raise
        except ValidationError as exc:
            messages.error(request, "；".join(exc.messages))
        else:
            messages.success(request, "需求已开始处理。")
    else:
        messages.error(request, "请求参数无效，请刷新页面后重试。")
    return redirect("demands:requirement_detail", pk=requirement.pk)


@login_required
@require_POST
def requirement_submit(request, pk):
    requirement = _get_requirement(request.user, pk)
    if requirement.assignee_id != request.user.id:
        raise PermissionDenied("只有需求负责人可以提交成果。")

    form = SubmissionForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            submission = submit_result(
                requirement_id=requirement.pk,
                actor=request.user,
                expected_lock_version=form.cleaned_data["lock_version"],
                result_url=form.cleaned_data["result_url"],
                description=form.cleaned_data["description"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                uploaded_files=form.cleaned_data["attachments"],
            )
        except PermissionDenied:
            raise
        except ValidationError as exc:
            form.add_error(None, "；".join(exc.messages))
        else:
            messages.success(request, f"成果 V{submission.version} 已提交，等待验收。")
            return redirect("demands:requirement_detail", pk=requirement.pk)

    return render(
        request,
        "demands/requirement_detail.html",
        _detail_context(requirement, request.user, submission_form=form),
    )


@login_required
def attachment_download(request, pk):
    visible_requirements = Requirement.objects.visible_to(request.user)
    attachment = get_object_or_404(
        SubmissionAttachment.objects.select_related(
            "submission__requirement__creator",
            "submission__requirement__assignee",
        ).filter(submission__requirement__in=visible_requirements),
        pk=pk,
    )
    try:
        file_handle = attachment.file.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("附件文件不存在。") from exc

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=attachment.original_name,
        content_type="application/octet-stream",
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def requirement_review(request, pk):
    requirement = _get_requirement(request.user, pk)
    if requirement.creator_id != request.user.id:
        raise PermissionDenied("只有需求提出者可以验收。")

    criterion_initial = _review_initial(requirement)
    form = ReviewDecisionForm(request.POST)
    formset = ReviewCriterionFormSet(
        request.POST,
        initial=criterion_initial,
        prefix="review_items",
    )
    if form.is_valid() and formset.is_valid():
        results = {
            item_form.cleaned_data["criterion_id"]: {
                "passed": item_form.cleaned_data["passed"],
                "comment": item_form.cleaned_data["comment"],
            }
            for item_form in formset
        }
        try:
            review = review_submission(
                requirement_id=requirement.pk,
                submission_id=form.cleaned_data["submission_id"],
                actor=request.user,
                expected_lock_version=form.cleaned_data["lock_version"],
                decision=form.cleaned_data["decision"],
                results=results,
                return_reason=form.cleaned_data["return_reason"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except PermissionDenied:
            raise
        except ValidationError as exc:
            form.add_error(None, "；".join(exc.messages))
        else:
            message = (
                "验收已通过，需求已完成。"
                if review.decision == Review.Decision.APPROVED
                else "成果已退回，等待负责人修改。"
            )
            messages.success(request, message)
            return redirect("demands:requirement_detail", pk=requirement.pk)

    return render(
        request,
        "demands/requirement_detail.html",
        _detail_context(
            requirement,
            request.user,
            review_form=form,
            review_formset=formset,
        ),
    )
