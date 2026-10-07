from .models import Requirement, Review


def latest_submission_and_decision(requirement):
    submissions = list(requirement.submissions.all())
    if not submissions:
        return None, None

    latest_submission = submissions[-1]
    try:
        decision = latest_submission.review.decision
    except Review.DoesNotExist:
        decision = None
    return latest_submission, decision


def decorate_requirement(requirement):
    latest_submission, latest_decision = latest_submission_and_decision(requirement)
    requirement.latest_submission_for_ui = latest_submission
    requirement.latest_review_decision_for_ui = latest_decision

    if requirement.status == Requirement.Status.PENDING:
        phase = "waiting"
        phase_label = "等待处理"
        creator_hint = "等待负责人开始处理"
        assignee_hint = "等待处理：请确认并开始需求"
    elif requirement.status == Requirement.Status.IN_PROGRESS:
        if latest_decision == Review.Decision.RETURNED:
            phase = "returned"
            phase_label = "退回修改中"
            creator_hint = "已退回，等待负责人修改后重新提交"
            assignee_hint = "已退回：请根据审核意见修改并重新提交"
        else:
            phase = "processing"
            phase_label = "处理中"
            creator_hint = "处理中：等待负责人提交成果"
            assignee_hint = "处理中：完成后请提交成果"
    elif requirement.status == Requirement.Status.IN_REVIEW:
        phase = "reviewing"
        phase_label = "审核中"
        creator_hint = "等待审核：请逐项检查验收条件"
        assignee_hint = "审核中：等待需求提出者验收"
    else:
        phase = "completed"
        phase_label = "已完成"
        creator_hint = "已完成：成果已通过全部验收条件"
        assignee_hint = "已完成：成果已通过验收"

    requirement.workflow_phase_for_ui = phase
    requirement.workflow_label_for_ui = phase_label
    requirement.creator_hint_for_ui = creator_hint
    requirement.assignee_hint_for_ui = assignee_hint
    return requirement


def user_action_hint(requirement, user):
    if requirement.creator_id == user.id:
        return requirement.creator_hint_for_ui
    return requirement.assignee_hint_for_ui
