from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from .models import RegistrationRequest
from .services import BUSINESS_ADMIN_GROUP, approve_registration


User = get_user_model()


class RegistrationTests(TestCase):
    def registration_data(self, **overrides):
        data = {
            "username": "new-user",
            "email": "new@example.com",
            "password1": "Strong-pass-8291",
            "password2": "Strong-pass-8291",
        }
        data.update(overrides)
        return data

    def test_registration_creates_inactive_pending_user(self):
        response = self.client.post(reverse("accounts:register"), self.registration_data())

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="new-user")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.registration_request.status, RegistrationRequest.Status.PENDING)

    def test_admin_request_requires_reason(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(requested_admin="on", admin_request_reason=""),
        )

        self.assertContains(response, "申请业务管理员时必须填写理由")
        self.assertFalse(User.objects.filter(username="new-user").exists())

    def test_superuser_can_approve_business_admin_without_creating_superuser(self):
        superuser = User.objects.create_superuser("root", "root@example.com", "password")
        user = User.objects.create_user("candidate", "candidate@example.com", "password", is_active=False)
        application = RegistrationRequest.objects.create(
            user=user,
            requested_admin=True,
            admin_request_reason="负责本团队需求流转。",
        )

        approve_registration(application.pk, superuser, as_admin=True)

        user.refresh_from_db()
        application.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name=BUSINESS_ADMIN_GROUP).exists())
        self.assertEqual(application.status, RegistrationRequest.Status.APPROVED)
        self.assertTrue(application.approved_as_admin)

    def test_business_admin_can_approve_member_but_not_another_admin(self):
        superuser = User.objects.create_superuser("root", "root@example.com", "password")
        approver = User.objects.create_user("approver", "approver@example.com", "password", is_active=False)
        approver_request = RegistrationRequest.objects.create(
            user=approver,
            requested_admin=True,
            admin_request_reason="负责成员审批。",
        )
        approve_registration(approver_request.pk, superuser, as_admin=True)
        approver.refresh_from_db()

        self.client.force_login(approver)
        admin_page = self.client.get(
            reverse("admin:accounts_registrationrequest_changelist")
        )
        self.assertEqual(admin_page.status_code, 200)
        self.assertContains(admin_page, "批准为普通成员")
        self.assertNotContains(admin_page, "批准为业务管理员（仅超级管理员）")

        member = User.objects.create_user("member", "member@example.com", "password", is_active=False)
        member_request = RegistrationRequest.objects.create(user=member)
        approve_registration(member_request.pk, approver)
        member.refresh_from_db()
        self.assertTrue(member.is_active)
        self.assertFalse(member.is_staff)

        candidate = User.objects.create_user("next-admin", "next@example.com", "password", is_active=False)
        candidate_request = RegistrationRequest.objects.create(
            user=candidate,
            requested_admin=True,
            admin_request_reason="协助管理。",
        )
        with self.assertRaises(PermissionDenied):
            approve_registration(candidate_request.pk, approver, as_admin=True)

        self.assertTrue(Group.objects.filter(name=BUSINESS_ADMIN_GROUP).exists())
