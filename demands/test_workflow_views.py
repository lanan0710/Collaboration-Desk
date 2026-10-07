import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Requirement, Review, Submission
from .services import (
    create_requirement,
    review_submission,
    start_requirement,
    submit_result,
)


class RequirementWorkflowViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.creator = user_model.objects.create_user(username="workflow-creator")
        self.assignee = user_model.objects.create_user(username="workflow-assignee")
        self.outsider = user_model.objects.create_user(username="workflow-outsider")
        self.requirement = create_requirement(
            actor=self.creator,
            assignee=self.assignee,
            title="状态化详情页需求",
            description="验证操作入口只在正确的角色和状态下显示。",
            criterion_texts=["主要流程可以正常使用", "退回意见清晰可执行"],
        )

    @property
    def detail_url(self):
        return reverse(
            "demands:requirement_detail",
            args=[self.requirement.pk],
        )

    @property
    def action_urls(self):
        return {
            "start": reverse(
                "demands:requirement_start",
                args=[self.requirement.pk],
            ),
            "submit": reverse(
                "demands:requirement_submit",
                args=[self.requirement.pk],
            ),
            "review": reverse(
                "demands:requirement_review",
                args=[self.requirement.pk],
            ),
        }

    def assert_visible_actions(self, user, *expected_actions):
        self.client.force_login(user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        expected_actions = set(expected_actions)
        for action_name, action_url in self.action_urls.items():
            form_action = f'action="{action_url}"'
            if action_name in expected_actions:
                self.assertContains(response, form_action)
                self.assertTrue(response.context[f"can_{action_name}"])
            else:
                self.assertNotContains(response, form_action)
                self.assertFalse(response.context[f"can_{action_name}"])
        return response

    def submit_via_service(self, result_url="https://example.com/result-v1"):
        self.requirement.refresh_from_db()
        return submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url=result_url,
            description="已完成本轮开发和验证。",
            idempotency_key=uuid.uuid4(),
        )

    def review_payload(self, submission, *, decision, failed_index=None):
        self.requirement.refresh_from_db()
        criteria = list(self.requirement.criteria.all())
        payload = {
            "decision": decision,
            "return_reason": (
                "第二条未通过，请补充可执行的退回说明。"
                if decision == Review.Decision.RETURNED
                else ""
            ),
            "lock_version": str(self.requirement.lock_version),
            "submission_id": str(submission.pk),
            "idempotency_key": str(uuid.uuid4()),
            "review_items-TOTAL_FORMS": str(len(criteria)),
            "review_items-INITIAL_FORMS": "0",
            "review_items-MIN_NUM_FORMS": "0",
            "review_items-MAX_NUM_FORMS": "20",
        }
        for index, criterion in enumerate(criteria):
            passed = index != failed_index
            payload.update(
                {
                    f"review_items-{index}-criterion_id": str(criterion.pk),
                    f"review_items-{index}-criterion_text": criterion.content,
                    f"review_items-{index}-passed": "true" if passed else "false",
                    f"review_items-{index}-comment": (
                        "请补充具体修改步骤。" if not passed else ""
                    ),
                }
            )
        return payload

    def return_v1_via_view(self):
        start_requirement(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
        )
        submission = self.submit_via_service()
        self.client.force_login(self.creator)
        response = self.client.post(
            self.action_urls["review"],
            self.review_payload(
                submission,
                decision=Review.Decision.RETURNED,
                failed_index=1,
            ),
        )
        self.assertRedirects(response, self.detail_url)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.IN_PROGRESS)
        return submission

    def test_action_forms_follow_role_and_workflow_state(self):
        # 待处理：只有负责人可以开始，提出者只查看进度。
        self.assert_visible_actions(self.creator)
        self.assert_visible_actions(self.assignee, "start")

        start_requirement(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
        )

        # 处理中：只有负责人可以提交成果。
        self.assert_visible_actions(self.creator)
        self.assert_visible_actions(self.assignee, "submit")

        submission_v1 = self.submit_via_service()

        # 审核中：只有提出者可以逐项审核。
        self.assert_visible_actions(self.creator, "review")
        self.assert_visible_actions(self.assignee)

        self.requirement.refresh_from_db()
        criteria = list(self.requirement.criteria.all())
        review_submission(
            requirement_id=self.requirement.pk,
            submission_id=submission_v1.pk,
            actor=self.creator,
            expected_lock_version=self.requirement.lock_version,
            decision=Review.Decision.RETURNED,
            results={
                criterion.pk: {
                    "passed": index == 0,
                    "comment": "" if index == 0 else "请补充具体修改步骤。",
                }
                for index, criterion in enumerate(criteria)
            },
            return_reason="第二条未通过，请补充可执行的退回说明。",
            idempotency_key=uuid.uuid4(),
        )

        # 退回后仍是进行中，但入口只回到负责人一侧，并显示重新提交。
        creator_response = self.assert_visible_actions(self.creator)
        assignee_response = self.assert_visible_actions(self.assignee, "submit")
        self.assertContains(creator_response, "已退回，等待负责人修改后重新提交")
        self.assertContains(assignee_response, "修改后重新提交成果")

        submission_v2 = self.submit_via_service("https://example.com/result-v2")
        self.requirement.refresh_from_db()
        review_submission(
            requirement_id=self.requirement.pk,
            submission_id=submission_v2.pk,
            actor=self.creator,
            expected_lock_version=self.requirement.lock_version,
            decision=Review.Decision.APPROVED,
            results={
                criterion.pk: {"passed": True, "comment": ""}
                for criterion in criteria
            },
            idempotency_key=uuid.uuid4(),
        )

        # 已完成：双方详情页均不再提供任何状态动作。
        for user in (self.creator, self.assignee):
            response = self.assert_visible_actions(user)
            self.assertContains(response, "已完成：成果已通过")

    def test_action_urls_only_accept_post(self):
        self.client.force_login(self.assignee)
        self.assertEqual(self.client.get(self.action_urls["start"]).status_code, 405)
        self.assertEqual(self.client.get(self.action_urls["submit"]).status_code, 405)

        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(self.action_urls["review"]).status_code, 405)

    def test_assignee_can_start_requirement_with_post(self):
        self.client.force_login(self.assignee)

        response = self.client.post(
            self.action_urls["start"],
            {"lock_version": str(self.requirement.lock_version)},
        )

        self.assertRedirects(response, self.detail_url)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.IN_PROGRESS)
        self.assertEqual(self.requirement.lock_version, 2)
        self.assertTrue(self.requirement.logs.filter(action="start").exists())

    def test_assignee_can_submit_v1_with_post(self):
        start_requirement(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
        )
        self.requirement.refresh_from_db()
        self.client.force_login(self.assignee)

        response = self.client.post(
            self.action_urls["submit"],
            {
                "result_url": "https://example.com/view-v1",
                "description": "通过网络交互层提交第一版成果。",
                "lock_version": str(self.requirement.lock_version),
                "idempotency_key": str(uuid.uuid4()),
            },
        )

        self.assertRedirects(response, self.detail_url)
        self.requirement.refresh_from_db()
        submission = self.requirement.submissions.get()
        self.assertEqual(self.requirement.status, Requirement.Status.IN_REVIEW)
        self.assertEqual(submission.version, 1)
        self.assertEqual(submission.submitted_by, self.assignee)
        self.assertEqual(submission.result_url, "https://example.com/view-v1")

    def test_return_is_visible_and_only_assignee_can_resubmit(self):
        submission_v1 = self.return_v1_via_view()

        self.client.force_login(self.creator)
        home_response = self.client.get(reverse("demands:home"))
        detail_response = self.client.get(self.detail_url)
        self.assertContains(home_response, "退回修改中")
        self.assertContains(home_response, "已退回，等待负责人修改后重新提交")
        self.assertContains(detail_response, "第二条未通过，请补充可执行的退回说明")
        self.assertNotContains(
            detail_response,
            f'action="{self.action_urls["submit"]}"',
        )

        self.requirement.refresh_from_db()
        forbidden_response = self.client.post(
            self.action_urls["submit"],
            {
                "result_url": "https://example.com/forged-v2",
                "description": "提出者不应能代替负责人重新提交。",
                "lock_version": str(self.requirement.lock_version),
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(forbidden_response.status_code, 403)
        self.assertEqual(Submission.objects.count(), 1)

        self.client.force_login(self.assignee)
        assignee_detail = self.client.get(self.detail_url)
        self.assertContains(assignee_detail, "修改后重新提交成果")
        response = self.client.post(
            self.action_urls["submit"],
            {
                "result_url": "https://example.com/view-v2",
                "description": "已按退回意见修改。",
                "lock_version": str(self.requirement.lock_version),
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertRedirects(response, self.detail_url)
        submission_v2 = Submission.objects.get(requirement=self.requirement, version=2)
        self.assertEqual(submission_v1.version, 1)
        self.assertEqual(submission_v2.submitted_by, self.assignee)

    def test_approved_requirement_has_no_remaining_actions(self):
        self.return_v1_via_view()

        self.requirement.refresh_from_db()
        submission_v2 = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="https://example.com/final-v2",
            description="已处理全部退回意见。",
            idempotency_key=uuid.uuid4(),
        )
        self.client.force_login(self.creator)
        approve_response = self.client.post(
            self.action_urls["review"],
            self.review_payload(
                submission_v2,
                decision=Review.Decision.APPROVED,
            ),
        )
        self.assertRedirects(approve_response, self.detail_url)

        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.COMPLETED)
        for user in (self.creator, self.assignee):
            response = self.assert_visible_actions(user)
            self.assertContains(response, "已完成：成果已通过")

