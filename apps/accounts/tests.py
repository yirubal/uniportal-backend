from unittest.mock import patch

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

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
