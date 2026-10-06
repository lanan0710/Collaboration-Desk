import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from .models import Requirement, Review, Submission
from .services import (
    StaleRequirementError,
    create_requirement,
    review_submission,
    start_requirement,
    submit_result,
)


class RequirementWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.creator = user_model.objects.create_user(username="creator")
        self.assignee = user_model.objects.create_user(username="assignee")
        self.outsider = user_model.objects.create_user(username="outsider")
        self.requirement = create_requirement(
            actor=self.creator,
            assignee=self.assignee,
            title="支持个人需求状态筛选",
            description="列表只显示本人提出或负责的需求。",
            criterion_texts=["状态筛选正确", "返回后保留筛选"],
        )

    def result_payload(self, *, all_passed):
        criteria = list(self.requirement.criteria.all())
        return {
            criterion.id: {
                "passed": all_passed or index == 0,
                "comment": "" if all_passed or index == 0 else "请保留返回前的筛选条件",
            }
            for index, criterion in enumerate(criteria)
        }

    def test_only_related_users_can_see_requirement(self):
        self.assertTrue(Requirement.objects.visible_to(self.creator).exists())
        self.assertTrue(Requirement.objects.visible_to(self.assignee).exists())
        self.assertFalse(Requirement.objects.visible_to(self.outsider).exists())

    def test_only_assignee_can_start_requirement(self):
        with self.assertRaises(PermissionDenied):
            start_requirement(
                requirement_id=self.requirement.id,
                actor=self.outsider,
                expected_lock_version=1,
            )

        started = start_requirement(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=1,
        )
        self.assertEqual(started.status, Requirement.Status.IN_PROGRESS)
        self.assertEqual(started.lock_version, 2)

    def test_stale_page_cannot_change_state(self):
        with self.assertRaises(StaleRequirementError):
            start_requirement(
                requirement_id=self.requirement.id,
                actor=self.assignee,
                expected_lock_version=99,
            )

    def test_return_resubmit_and_approve_preserves_every_version(self):
        started = start_requirement(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=1,
        )
        submit_key = uuid.uuid4()
        submission_v1 = submit_result(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=started.lock_version,
            result_url="https://example.com/v1",
            description="第一版成果",
            idempotency_key=submit_key,
        )

        duplicate = submit_result(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=started.lock_version,
            result_url="https://example.com/v1",
            description="第一版成果",
            idempotency_key=submit_key,
        )
        self.assertEqual(duplicate.id, submission_v1.id)
        self.assertEqual(Submission.objects.count(), 1)

        self.requirement.refresh_from_db()
        review_submission(
            requirement_id=self.requirement.id,
            submission_id=submission_v1.id,
            actor=self.creator,
            expected_lock_version=self.requirement.lock_version,
            decision=Review.Decision.RETURNED,
            results=self.result_payload(all_passed=False),
            return_reason="返回列表后筛选条件丢失，请在跳转时保留查询参数。",
            idempotency_key=uuid.uuid4(),
        )

        self.requirement.refresh_from_db()
        submission_v2 = submit_result(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="https://example.com/v2",
            description="已修复筛选条件保留问题",
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(submission_v2.version, 2)

        self.requirement.refresh_from_db()
        review_submission(
            requirement_id=self.requirement.id,
            submission_id=submission_v2.id,
            actor=self.creator,
            expected_lock_version=self.requirement.lock_version,
            decision=Review.Decision.APPROVED,
            results=self.result_payload(all_passed=True),
            idempotency_key=uuid.uuid4(),
        )

        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.COMPLETED)
        self.assertEqual(list(self.requirement.submissions.values_list("version", flat=True)), [1, 2])
        self.assertEqual(Review.objects.count(), 2)
        self.assertEqual(self.requirement.logs.filter(action="submit").count(), 2)

    def test_return_requires_failed_item_and_reason(self):
        started = start_requirement(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=1,
        )
        submission = submit_result(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=started.lock_version,
            result_url="https://example.com/v1",
            description="第一版成果",
            idempotency_key=uuid.uuid4(),
        )
        self.requirement.refresh_from_db()

        with self.assertRaises(ValidationError):
            review_submission(
                requirement_id=self.requirement.id,
                submission_id=submission.id,
                actor=self.creator,
                expected_lock_version=self.requirement.lock_version,
                decision=Review.Decision.RETURNED,
                results=self.result_payload(all_passed=True),
                return_reason="不能在全部通过时退回",
                idempotency_key=uuid.uuid4(),
            )

        with self.assertRaises(ValidationError):
            review_submission(
                requirement_id=self.requirement.id,
                submission_id=submission.id,
                actor=self.creator,
                expected_lock_version=self.requirement.lock_version,
                decision=Review.Decision.RETURNED,
                results=self.result_payload(all_passed=False),
                return_reason="",
                idempotency_key=uuid.uuid4(),
            )

    def test_submission_is_immutable(self):
        started = start_requirement(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=1,
        )
        submission = submit_result(
            requirement_id=self.requirement.id,
            actor=self.assignee,
            expected_lock_version=started.lock_version,
            result_url="https://example.com/v1",
            description="第一版成果",
            idempotency_key=uuid.uuid4(),
        )
        submission.description = "试图覆盖旧版本"
        with self.assertRaises(ValidationError):
            submission.save()
