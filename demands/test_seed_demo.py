from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .management.commands.seed_demo_data import DEMO_PASSWORD
from .models import Requirement, Review


class SeedDemoDataCommandTests(TestCase):
    def test_command_creates_repeatable_acceptance_dataset(self):
        output = StringIO()
        call_command("seed_demo_data", stdout=output)

        user_model = get_user_model()
        for username in ("demo_proposer", "demo_assignee", "demo_outsider"):
            user = user_model.objects.get(username=username)
            self.assertTrue(user.is_active)
            self.assertTrue(user.check_password(DEMO_PASSWORD))

        demo_requirements = Requirement.objects.filter(title__startswith="[演示]")
        self.assertEqual(demo_requirements.count(), 4)
        self.assertEqual(
            set(demo_requirements.values_list("status", flat=True)),
            {
                Requirement.Status.PENDING,
                Requirement.Status.IN_PROGRESS,
                Requirement.Status.IN_REVIEW,
                Requirement.Status.COMPLETED,
            },
        )
        pending = demo_requirements.get(status=Requirement.Status.PENDING)
        self.assertGreaterEqual(pending.criteria.count(), 3)

        completed = demo_requirements.get(status=Requirement.Status.COMPLETED)
        self.assertEqual(
            list(completed.submissions.values_list("version", flat=True)),
            [1, 2],
        )
        self.assertEqual(
            list(
                completed.submissions.values_list("review__decision", flat=True)
            ),
            [Review.Decision.RETURNED, Review.Decision.APPROVED],
        )

        initial_counts = (
            user_model.objects.count(),
            Requirement.objects.count(),
            completed.submissions.count(),
            completed.logs.count(),
        )
        call_command("seed_demo_data", stdout=StringIO())
        completed.refresh_from_db()
        self.assertEqual(
            (
                user_model.objects.count(),
                Requirement.objects.count(),
                completed.submissions.count(),
                completed.logs.count(),
            ),
            initial_counts,
        )
