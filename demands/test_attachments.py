import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .attachment_rules import MAX_ATTACHMENT_SIZE
from .models import Requirement, Submission, SubmissionAttachment
from .services import create_requirement, start_requirement, submit_result


class SubmissionAttachmentTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        user_model = get_user_model()
        self.creator = user_model.objects.create_user(username="attachment-creator")
        self.assignee = user_model.objects.create_user(username="attachment-assignee")
        self.outsider = user_model.objects.create_user(username="attachment-outsider")
        self.requirement = create_requirement(
            actor=self.creator,
            assignee=self.assignee,
            title="支持成果附件",
            description="负责人既可以提供成果链接，也可以直接上传附件。",
            criterion_texts=["成果材料可以安全下载"],
        )
        self.requirement = start_requirement(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
        )
        self.client.force_login(self.assignee)

    @property
    def submit_url(self):
        return reverse("demands:requirement_submit", args=[self.requirement.pk])

    @property
    def detail_url(self):
        return reverse("demands:requirement_detail", args=[self.requirement.pk])

    def submission_payload(self, **overrides):
        payload = {
            "result_url": "",
            "description": "提交本轮成果材料。",
            "lock_version": str(self.requirement.lock_version),
            "idempotency_key": str(uuid.uuid4()),
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def uploaded_file(name="evidence.txt", content=b"attachment evidence"):
        return SimpleUploadedFile(name, content, content_type="application/octet-stream")

    def assert_requirement_unchanged(self):
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.IN_PROGRESS)
        self.assertEqual(self.requirement.lock_version, 2)
        self.assertEqual(Submission.objects.count(), 0)
        self.assertEqual(SubmissionAttachment.objects.count(), 0)

    def test_attachment_only_post_creates_v1_and_lists_persisted_files(self):
        response = self.client.post(
            self.submit_url,
            self.submission_payload(
                attachments=[
                    self.uploaded_file("design.pdf", b"pdf material"),
                    self.uploaded_file("screenshots.zip", b"zip material"),
                ]
            ),
        )

        self.assertRedirects(response, self.detail_url)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.status, Requirement.Status.IN_REVIEW)
        submission = Submission.objects.get(requirement=self.requirement)
        self.assertEqual(submission.version, 1)
        self.assertEqual(submission.result_url, "")

        attachments = list(submission.attachments.all())
        self.assertEqual(
            [attachment.original_name for attachment in attachments],
            ["design.pdf", "screenshots.zip"],
        )
        self.assertEqual(
            [attachment.size for attachment in attachments],
            [len(b"pdf material"), len(b"zip material")],
        )
        for attachment in attachments:
            self.assertTrue(attachment.file.storage.exists(attachment.file.name))

        detail_response = self.client.get(self.detail_url)
        self.assertContains(detail_response, "design.pdf")
        self.assertContains(detail_response, "screenshots.zip")
        for attachment in attachments:
            self.assertContains(
                detail_response,
                reverse("demands:attachment_download", args=[attachment.pk]),
            )

    def test_link_only_submission_still_works(self):
        response = self.client.post(
            self.submit_url,
            self.submission_payload(result_url="https://example.com/result-v1"),
        )

        self.assertRedirects(response, self.detail_url)
        submission = Submission.objects.get(requirement=self.requirement)
        self.assertEqual(submission.result_url, "https://example.com/result-v1")
        self.assertFalse(submission.attachments.exists())

    def test_empty_link_and_attachments_are_rejected_without_state_change(self):
        response = self.client.post(self.submit_url, self.submission_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成果链接和附件至少需要提供一项")
        self.assert_requirement_unchanged()

    def test_more_than_five_attachments_are_rejected(self):
        response = self.client.post(
            self.submit_url,
            self.submission_payload(
                attachments=[
                    self.uploaded_file(f"evidence-{index}.txt", f"file {index}".encode())
                    for index in range(6)
                ]
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "一次最多上传 5 个附件")
        self.assert_requirement_unchanged()
        self.assertEqual(list(Path(self.media_directory.name).rglob("*")), [])

    def test_dangerous_extension_is_rejected(self):
        response = self.client.post(
            self.submit_url,
            self.submission_payload(
                attachments=[self.uploaded_file("installer.exe", b"not executable")]
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "文件类型不受支持")
        self.assert_requirement_unchanged()

    def test_oversized_attachment_is_rejected_by_service(self):
        oversized_file = self.uploaded_file("oversized.pdf", b"small test body")
        oversized_file.size = MAX_ATTACHMENT_SIZE + 1

        with self.assertRaisesMessage(ValidationError, "超过 20 MiB"):
            submit_result(
                requirement_id=self.requirement.pk,
                actor=self.assignee,
                expected_lock_version=self.requirement.lock_version,
                result_url="",
                description="超大附件不应创建提交。",
                idempotency_key=uuid.uuid4(),
                uploaded_files=[oversized_file],
            )

        self.assert_requirement_unchanged()

    def test_same_idempotency_key_does_not_duplicate_submission_or_attachment(self):
        idempotency_key = uuid.uuid4()
        first = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="可安全重试的附件提交。",
            idempotency_key=idempotency_key,
            uploaded_files=[self.uploaded_file("retry.txt", b"same payload")],
        )

        retried = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="可安全重试的附件提交。",
            idempotency_key=idempotency_key,
            uploaded_files=[self.uploaded_file("retry.txt", b"same payload")],
        )

        self.assertEqual(retried.pk, first.pk)
        self.assertEqual(Submission.objects.count(), 1)
        self.assertEqual(SubmissionAttachment.objects.count(), 1)
        self.assertEqual(
            len([path for path in Path(self.media_directory.name).rglob("*") if path.is_file()]),
            1,
        )

    def test_same_idempotency_key_rejects_different_payload(self):
        idempotency_key = uuid.uuid4()
        submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="原始说明。",
            idempotency_key=idempotency_key,
            uploaded_files=[self.uploaded_file("retry.txt", b"same size")],
        )

        with self.assertRaisesMessage(ValidationError, "与原成果提交内容不匹配"):
            submit_result(
                requirement_id=self.requirement.pk,
                actor=self.assignee,
                expected_lock_version=self.requirement.lock_version,
                result_url="",
                description="不同说明。",
                idempotency_key=idempotency_key,
                uploaded_files=[self.uploaded_file("retry.txt", b"same size")],
            )

        self.assertEqual(Submission.objects.count(), 1)
        self.assertEqual(SubmissionAttachment.objects.count(), 1)

    def test_idempotency_retry_still_checks_actor_permission(self):
        idempotency_key = uuid.uuid4()
        submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="受权限保护的幂等请求。",
            idempotency_key=idempotency_key,
            uploaded_files=[self.uploaded_file("permission.txt", b"protected")],
        )

        with self.assertRaises(PermissionDenied):
            submit_result(
                requirement_id=self.requirement.pk,
                actor=self.outsider,
                expected_lock_version=self.requirement.lock_version,
                result_url="",
                description="受权限保护的幂等请求。",
                idempotency_key=idempotency_key,
                uploaded_files=[self.uploaded_file("permission.txt", b"protected")],
            )

    def test_uploaded_files_are_cleaned_up_when_transaction_fails(self):
        with patch(
            "demands.services.OperationLog.objects.create",
            side_effect=RuntimeError("simulated database failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "simulated database failure"):
                submit_result(
                    requirement_id=self.requirement.pk,
                    actor=self.assignee,
                    expected_lock_version=self.requirement.lock_version,
                    result_url="",
                    description="该事务应完整回滚。",
                    idempotency_key=uuid.uuid4(),
                    uploaded_files=[self.uploaded_file("rollback.txt", b"temporary")],
                )

        self.assert_requirement_unchanged()
        stored_files = [
            path for path in Path(self.media_directory.name).rglob("*") if path.is_file()
        ]
        self.assertEqual(stored_files, [])

    def test_download_requires_related_authenticated_user_and_sets_safe_headers(self):
        submission = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="供相关人员下载。",
            idempotency_key=uuid.uuid4(),
            uploaded_files=[self.uploaded_file("download.txt", b"download body")],
        )
        attachment = submission.attachments.get()
        download_url = reverse("demands:attachment_download", args=[attachment.pk])

        for user in (self.creator, self.assignee):
            self.client.force_login(user)
            response = self.client.get(download_url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("download.txt", response.headers["Content-Disposition"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(b"".join(response.streaming_content), b"download body")
            response.close()

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(download_url).status_code, 404)

        self.client.logout()
        response = self.client.get(download_url)
        self.assertRedirects(response, f"{reverse('login')}?next={download_url}")

    def test_attachment_instance_cannot_be_modified_or_deleted(self):
        submission = submit_result(
            requirement_id=self.requirement.pk,
            actor=self.assignee,
            expected_lock_version=self.requirement.lock_version,
            result_url="",
            description="不可变附件。",
            idempotency_key=uuid.uuid4(),
            uploaded_files=[self.uploaded_file("immutable.txt", b"fixed content")],
        )
        attachment = submission.attachments.get()
        stored_name = attachment.file.name

        attachment.original_name = "renamed.txt"
        with self.assertRaisesMessage(ValidationError, "历史附件不可修改"):
            attachment.save()
        with self.assertRaisesMessage(ValidationError, "历史附件不可删除"):
            attachment.delete()

        persisted = SubmissionAttachment.objects.get(pk=attachment.pk)
        self.assertEqual(persisted.original_name, "immutable.txt")
        self.assertTrue(persisted.file.storage.exists(stored_name))

