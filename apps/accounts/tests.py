from unittest.mock import patch

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.utils import timezone
from datetime import timedelta
from io import StringIO

from .admin import SubscriptionRequestAdmin
from .models import Student, SubscriptionPlan, SubscriptionRequest


class SubscriptionRequestDeletionTests(TestCase):
    def test_deleting_rejected_subscription_request_does_not_activate_student(self):
        student = Student.objects.create(
            telegram_id=987654321,
            first_name='Free',
            username='free_student',
            subscription_status=Student.SUBSCRIPTION_FREE,
        )
        plan = SubscriptionPlan.objects.create(
            plan_id=SubscriptionPlan.PLAN_SEMESTER,
            name='Semester Pass',
            price=500,
            days=120,
            is_active=True,
        )
        sub_request = SubscriptionRequest.objects.create(
            student=student,
            plan=plan,
            reference='UNI-DEL01',
            amount=plan.price,
            status=SubscriptionRequest.STATUS_REJECTED,
        )

        sub_request.delete()

        student.refresh_from_db()
        self.assertEqual(student.subscription_status, Student.SUBSCRIPTION_FREE)
        self.assertIsNone(student.subscription_expiry)

    @patch('apps.accounts.admin.SubscriptionRequestAdmin.message_user')
    def test_direct_admin_status_edit_to_approved_does_not_activate_student(self, message_user):
        student = Student.objects.create(
            telegram_id=987654322,
            first_name='Still Free',
            username='still_free',
            subscription_status=Student.SUBSCRIPTION_FREE,
        )
        plan = SubscriptionPlan.objects.create(
            plan_id=SubscriptionPlan.PLAN_SEMESTER,
            name='Semester Pass',
            price=500,
            days=120,
            is_active=True,
        )
        sub_request = SubscriptionRequest.objects.create(
            student=student,
            plan=plan,
            reference='UNI-EDIT1',
            amount=plan.price,
            status=SubscriptionRequest.STATUS_PENDING,
        )
        request = RequestFactory().post('/admin/accounts/subscriptionrequest/')
        request.user = get_user_model().objects.create_user(username='admin')
        model_admin = SubscriptionRequestAdmin(SubscriptionRequest, django_admin.site)

        sub_request.status = SubscriptionRequest.STATUS_APPROVED
        model_admin.save_model(request, sub_request, form=None, change=True)

        student.refresh_from_db()
        sub_request.refresh_from_db()
        self.assertEqual(student.subscription_status, Student.SUBSCRIPTION_FREE)
        self.assertIsNone(student.subscription_expiry)
        self.assertEqual(sub_request.status, SubscriptionRequest.STATUS_PENDING)
        message_user.assert_called_once()

    def test_repair_command_downgrades_premium_student_without_approved_request(self):
        student = Student.objects.create(
            telegram_id=987654323,
            first_name='Stale Premium',
            username='stale_premium',
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
            subscription_expiry=timezone.now() + timedelta(days=30),
        )
        plan = SubscriptionPlan.objects.create(
            plan_id=SubscriptionPlan.PLAN_SEMESTER,
            name='Semester Pass',
            price=500,
            days=120,
            is_active=True,
        )
        SubscriptionRequest.objects.create(
            student=student,
            plan=plan,
            reference='UNI-STALE',
            amount=plan.price,
            status=SubscriptionRequest.STATUS_REJECTED,
        )
        out = StringIO()

        call_command('repair_subscription_statuses', stdout=out)

        student.refresh_from_db()
        self.assertEqual(student.subscription_status, Student.SUBSCRIPTION_FREE)
        self.assertIsNone(student.subscription_expiry)
        self.assertIn('Repaired 1 student subscription state', out.getvalue())
