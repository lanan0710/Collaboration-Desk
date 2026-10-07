import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import OperationLog, Requirement, Review, Submission
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


class RequirementHomeViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.creator = user_model.objects.create_user(username="web-creator")
        self.assignee = user_model.objects.create_user(
            username="web-assignee",
            email="assignee@example.com",
        )
        self.inactive_user = user_model.objects.create_user(
            username="inactive-assignee",
            is_active=False,
        )
        self.client.force_login(self.creator)

    def home_payload(self, *, criteria=None, **overrides):
        criteria = ["第一条验收条件"] if criteria is None else criteria
        total_forms = max(1, len(criteria))
        data = {
            "title": "首页创建需求",
            "description": "验证首页表单能够调用业务服务。",
            "assignee": self.assignee.pk,
            "criteria-TOTAL_FORMS": str(total_forms),
            "criteria-INITIAL_FORMS": "0",
            "criteria-MIN_NUM_FORMS": "1",
            "criteria-MAX_NUM_FORMS": "20",
        }
        for index in range(total_forms):
            data[f"criteria-{index}-content"] = (
                criteria[index] if index < len(criteria) else ""
            )
        data.update(overrides)
        return data

    def test_anonymous_user_cannot_open_or_submit_home(self):
        self.client.logout()

        get_response = self.client.get(reverse("demands:home"))
        post_response = self.client.post(
            reverse("demands:home"),
            self.home_payload(
                title="匿名创建",
                description="不应被创建。",
                criteria=["不应被创建"],
            ),
        )

        self.assertRedirects(
            get_response,
            f"{reverse('login')}?next={reverse('demands:home')}",
        )
        self.assertRedirects(
            post_response,
            f"{reverse('login')}?next={reverse('demands:home')}",
        )
        self.assertFalse(Requirement.objects.filter(title="匿名创建").exists())

    def test_home_shows_create_form_with_only_eligible_assignees(self):
        response = self.client.get(reverse("demands:home"))

        self.assertEqual(response.status_code, 200)
        queryset = response.context["form"].fields["assignee"].queryset
        self.assertIn(self.assignee, queryset)
        self.assertNotIn(self.creator, queryset)
        self.assertNotIn(self.inactive_user, queryset)
        self.assertContains(response, 'id="assignee-search"')
        self.assertContains(response, "web-assignee（assignee@example.com）")
        self.assertContains(response, 'id="criterion-form-list"')

    def test_home_can_create_requirement_and_criteria(self):
        response = self.client.post(
            reverse("demands:home"),
            self.home_payload(criteria=["第一条验收条件", "第二条验收条件"]),
            follow=True,
        )

        self.assertRedirects(response, reverse("demands:home"))
        requirement = Requirement.objects.get(title="首页创建需求")
        self.assertEqual(requirement.creator, self.creator)
        self.assertEqual(requirement.assignee, self.assignee)
        self.assertEqual(
            list(requirement.criteria.values_list("content", flat=True)),
            ["第一条验收条件", "第二条验收条件"],
        )
        self.assertTrue(
            OperationLog.objects.filter(requirement=requirement, action="create").exists()
        )
        self.assertContains(response, "需求“首页创建需求”已创建")

    def test_home_rejects_empty_criteria(self):
        response = self.client.post(
            reverse("demands:home"),
            self.home_payload(
                criteria=[],
                title="无验收条件",
                description="该请求应被表单拒绝。",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "至少需要填写一条验收条件")
        self.assertFalse(Requirement.objects.filter(title="无验收条件").exists())

    def test_home_rejects_assigning_requirement_to_creator(self):
        response = self.client.post(
            reverse("demands:home"),
            self.home_payload(
                title="错误负责人",
                description="不能把自己指定为负责人。",
                assignee=self.creator.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "assignee",
            "请选择一个有效的负责人。",
        )
        self.assertFalse(Requirement.objects.filter(title="错误负责人").exists())

    def test_home_rejects_more_than_twenty_criteria(self):
        response = self.client.post(
            reverse("demands:home"),
            self.home_payload(
                criteria=[f"条件 {index}" for index in range(21)],
                title="条件过多",
                description="超过服务允许的最大数量。",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "验收条件最多填写 20 条")
        self.assertFalse(Requirement.objects.filter(title="条件过多").exists())

    def test_home_links_related_requirements_to_detail_page(self):
        requirement = create_requirement(
            actor=self.creator,
            assignee=self.assignee,
            title="可点击的需求",
            description="首页应提供详情链接。",
            criterion_texts=["能够进入详情页"],
        )

        response = self.client.get(reverse("demands:home"))

        self.assertContains(
            response,
            reverse("demands:requirement_detail", args=[requirement.pk]),
        )


class RequirementDetailViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.creator = user_model.objects.create_user(username="detail-creator")
        self.assignee = user_model.objects.create_user(username="detail-assignee")
        self.outsider = user_model.objects.create_user(username="detail-outsider")
        self.requirement = create_requirement(
            actor=self.creator,
            assignee=self.assignee,
            title="详情页需求",
            description="只有相关用户能够查看。",
            criterion_texts=["展示第一项", "展示第二项"],
        )

    def detail_url(self):
        return reverse("demands:requirement_detail", args=[self.requirement.pk])

    def test_creator_and_assignee_can_view_detail(self):
        for user in (self.creator, self.assignee):
            self.client.force_login(user)
            response = self.client.get(self.detail_url())
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "详情页需求")
            self.assertContains(response, "展示第一项")
            self.assertContains(response, "展示第二项")

    def test_outsider_receives_not_found_for_detail(self):
        self.client.force_login(self.outsider)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 404)

    def test_detail_displays_submission_and_each_review_result(self):
        started = start_requirement(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
        )
        submission = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=started.lock_version,
            result_url="https://example.com/detail-v1",
            description="详情页第一版成果",
            idempotency_key=uuid.uuid4(),
        )
        self.client.force_login(self.creator)

        pending_review_response = self.client.get(self.detail_url())
        self.assertContains(pending_review_response, "V1")
        self.assertContains(pending_review_response, "该版本尚未验收")

        self.requirement.refresh_from_db()
        criteria = list(self.requirement.criteria.all())
        review_submission(
            requirement_id=self.requirement.pk,
            submission_id=submission.pk,
            actor=self.creator,
            expected_lock_version=self.requirement.lock_version,
            decision=Review.Decision.RETURNED,
            results={
                criteria[0].pk: {"passed": True, "comment": ""},
                criteria[1].pk: {"passed": False, "comment": "需要补充测试。"},
            },
            return_reason="第二项尚未达到要求。",
            idempotency_key=uuid.uuid4(),
        )

        reviewed_response = self.client.get(self.detail_url())
        self.assertContains(reviewed_response, "第二项尚未达到要求")
        self.assertContains(reviewed_response, "展示第一项")
        self.assertContains(reviewed_response, "展示第二项")
        self.assertContains(reviewed_response, "需要补充测试")
