from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.admin import _approve_subscription_request
from apps.accounts.models import Student, SubscriptionPlan, SubscriptionRequest
from apps.api.views import _generate_jwt


@override_settings(TELEGRAM_BOT_TOKEN='test-token')
class SubscriptionRequestTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(
            telegram_id=123456,
            first_name='Test',
            username='testuser',
        )
        self.semester_plan = SubscriptionPlan.objects.create(
            plan_id=SubscriptionPlan.PLAN_SEMESTER,
            name='Semester Pass',
            price=500,
            days=120,
            is_active=True,
        )
        self.annual_plan = SubscriptionPlan.objects.create(
            plan_id=SubscriptionPlan.PLAN_ANNUAL,
            name='Full Year Pass',
            price=1200,
            days=365,
            is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_generate_jwt(self.student)}')

    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_creates_request_once_and_notifies_after_save(self, notify_created):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/subscription/request/',
                {
                    'plan': self.semester_plan.plan_id,
                    'payment_method': SubscriptionRequest.PAYMENT_TELEBIRR,
                    'paid_from': '0911000000',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SubscriptionRequest.objects.count(), 1)
        sub_request = SubscriptionRequest.objects.get()
        self.assertEqual(response.data['reference'], sub_request.reference)
        self.assertEqual(response.data['status'], SubscriptionRequest.STATUS_PENDING)
        notify_created.assert_called_once_with(sub_request)

    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_returns_existing_pending_request_instead_of_duplicate(self, notify_created):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(
                '/api/subscription/request/',
                {'plan': self.semester_plan.plan_id, 'paid_from': '0911000000'},
                format='json',
            )
        with self.captureOnCommitCallbacks(execute=True):
            second = self.client.post(
                '/api/subscription/request/',
                {'plan': self.annual_plan.plan_id, 'paid_from': '0911000000'},
                format='json',
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(SubscriptionRequest.objects.count(), 1)
        self.assertEqual(second.data['reference'], first.data['reference'])
        self.assertEqual(second.data['plan'], self.semester_plan.name)
        notify_created.assert_called_once()

    def test_get_returns_latest_active_request_status(self):
        sub_request = SubscriptionRequest.objects.create(
            student=self.student,
            plan=self.semester_plan,
            reference='UNI-11111',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_REJECTED,
        )

        response = self.client.get('/api/subscription/request/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_pending_request'])
        self.assertEqual(response.data['active_request']['reference'], sub_request.reference)
        self.assertEqual(response.data['active_request']['status'], SubscriptionRequest.STATUS_REJECTED)
        self.assertEqual(response.data['current_request']['status'], SubscriptionRequest.STATUS_REJECTED)
        self.assertIsNone(response.data['pending_request'])

    @patch('apps.accounts.admin.notify_subscription_approved')
    def test_admin_approval_updates_student_premium_status_for_profile(self, notify_approved):
        admin_user = get_user_model().objects.create_user(
            username='admin',
            password='password',
        )
        sub_request = SubscriptionRequest.objects.create(
            student=self.student,
            plan=self.semester_plan,
            reference='UNI-22222',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_PENDING,
        )

        _approve_subscription_request(sub_request, admin_user)
        response = self.client.get('/api/students/me/')

        self.student.refresh_from_db()
        sub_request.refresh_from_db()
        self.assertEqual(sub_request.status, SubscriptionRequest.STATUS_APPROVED)
        self.assertEqual(self.student.subscription_status, Student.SUBSCRIPTION_PREMIUM)
        self.assertTrue(response.data['is_premium'])
        self.assertEqual(response.data['subscription_status'], Student.SUBSCRIPTION_PREMIUM)
        notify_approved.assert_called_once_with(sub_request)
