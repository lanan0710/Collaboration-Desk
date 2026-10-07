import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from demands.models import Requirement, Review
from demands.services import (
    create_requirement,
    review_submission,
    start_requirement,
    submit_result,
)


DEMO_PASSWORD = "DemoPass!2026"
DEMO_USERS = (
    ("demo_proposer", "proposer@example.com"),
    ("demo_assignee", "assignee@example.com"),
    ("demo_outsider", "outsider@example.com"),
)
DEMO_NAMESPACE = uuid.UUID("878ca54c-bff7-4974-8ee1-67e0d105c6dc")


class Command(BaseCommand):
    help = "幂等创建官方验收所需的演示账号和各状态需求。"

    def _user(self, username, email):
        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_active": True},
        )
        changed_fields = []
        if user.email != email:
            user.email = email
            changed_fields.append("email")
        if not user.is_active:
            user.is_active = True
            changed_fields.append("is_active")
        user.set_password(DEMO_PASSWORD)
        changed_fields.append("password")
        user.save(update_fields=changed_fields)
        return user

    def _existing(self, creator, title):
        return Requirement.objects.filter(creator=creator, title=title).first()

    def _create(self, *, creator, assignee, title, description, criteria):
        existing = self._existing(creator, title)
        if existing:
            self.stdout.write(f"保留已有演示需求：{title}")
            return existing, False
        return (
            create_requirement(
                actor=creator,
                assignee=assignee,
                title=title,
                description=description,
                criterion_texts=criteria,
            ),
            True,
        )

    @staticmethod
    def _key(label):
        return uuid.uuid5(DEMO_NAMESPACE, label)

    def handle(self, *args, **options):
        users = {
            username: self._user(username, email)
            for username, email in DEMO_USERS
        }
        proposer = users["demo_proposer"]
        assignee = users["demo_assignee"]

        self._create(
            creator=proposer,
            assignee=assignee,
            title="[演示] 待处理需求",
            description="用于检查提出者编辑、负责人开始处理以及至少三条验收条件。",
            criteria=[
                "详情页能看到提出者和负责人",
                "提出者能在开始前修改需求",
                "负责人开始后验收标准被冻结",
            ],
        )

        in_progress, created = self._create(
            creator=proposer,
            assignee=assignee,
            title="[演示] 进行中需求",
            description="用于检查负责人提交成果前的进行中状态。",
            criteria=["负责人可以提交 HTTP/HTTPS 成果链接"],
        )
        if created:
            start_requirement(
                requirement_id=in_progress.pk,
                actor=assignee,
                expected_lock_version=in_progress.lock_version,
            )

        in_review, created = self._create(
            creator=proposer,
            assignee=assignee,
            title="[演示] 待验收需求",
            description="用于检查提出者逐项验收当前成果。",
            criteria=["成果页面能够访问", "完成说明清楚可执行"],
        )
        if created:
            in_review = start_requirement(
                requirement_id=in_review.pk,
                actor=assignee,
                expected_lock_version=in_review.lock_version,
            )
            submit_result(
                requirement_id=in_review.pk,
                actor=assignee,
                expected_lock_version=in_review.lock_version,
                result_url="https://example.com/demo/in-review",
                description="演示待验收成果，包含访问地址与验证说明。",
                idempotency_key=self._key("in-review-v1"),
            )

        completed, created = self._create(
            creator=proposer,
            assignee=assignee,
            title="[演示] V1 退回后 V2 通过",
            description="完整展示提交、逐项退回、重新提交和验收完成的历史链。",
            criteria=["页面展示版本号", "旧版本不会被覆盖", "逐项反馈可回看"],
        )
        if created:
            completed = start_requirement(
                requirement_id=completed.pk,
                actor=assignee,
                expected_lock_version=completed.lock_version,
            )
            v1 = submit_result(
                requirement_id=completed.pk,
                actor=assignee,
                expected_lock_version=completed.lock_version,
                result_url="https://example.com/demo/v1",
                description="V1 完成页面与版本展示，逐项反馈仍待补充。",
                idempotency_key=self._key("completed-v1"),
            )
            completed.refresh_from_db()
            criteria = list(completed.criteria.all())
            review_submission(
                requirement_id=completed.pk,
                submission_id=v1.pk,
                actor=proposer,
                expected_lock_version=completed.lock_version,
                decision=Review.Decision.RETURNED,
                results={
                    criteria[0].pk: {"passed": True, "comment": "版本号展示正确。"},
                    criteria[1].pk: {"passed": True, "comment": "V1 已独立保存。"},
                    criteria[2].pk: {
                        "passed": False,
                        "comment": "请在详情页补充逐项反馈展示。",
                    },
                },
                return_reason="第三条验收条件尚未满足，请补充反馈展示后提交 V2。",
                idempotency_key=self._key("completed-review-v1"),
            )
            completed.refresh_from_db()
            v2 = submit_result(
                requirement_id=completed.pk,
                actor=assignee,
                expected_lock_version=completed.lock_version,
                result_url="https://example.com/demo/v2",
                description="V2 已补充逐项反馈展示，并保留 V1 历史。",
                idempotency_key=self._key("completed-v2"),
            )
            completed.refresh_from_db()
            review_submission(
                requirement_id=completed.pk,
                submission_id=v2.pk,
                actor=proposer,
                expected_lock_version=completed.lock_version,
                decision=Review.Decision.APPROVED,
                results={
                    criterion.pk: {"passed": True, "comment": "V2 验收通过。"}
                    for criterion in criteria
                },
                idempotency_key=self._key("completed-review-v2"),
            )

        self.stdout.write(self.style.SUCCESS("演示数据已就绪。"))
        self.stdout.write(
            "账号：demo_proposer / demo_assignee / demo_outsider；"
            f"统一密码：{DEMO_PASSWORD}"
        )
