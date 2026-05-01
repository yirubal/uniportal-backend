from unittest.mock import patch

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.admin import SubscriptionRequestAdmin, _approve_subscription_request
from apps.accounts.notifications import notify_subscription_rejected
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

    @patch('apps.accounts.admin.notify_subscription_rejected')
    @patch('apps.accounts.admin.SubscriptionRequestAdmin.message_user')
    def test_admin_bulk_reject_updates_selected_subscription_requests(self, message_user, notify_rejected):
        other_student = Student.objects.create(
            telegram_id=654321,
            first_name='Other',
            username='otheruser',
        )
        approved_student = Student.objects.create(
            telegram_id=111222,
            first_name='Approved',
            username='approveduser',
        )
        approved_student.activate_premium(self.semester_plan.days)
        first_pending = SubscriptionRequest.objects.create(
            student=self.student,
            plan=self.semester_plan,
            reference='UNI-33333',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_PENDING,
        )
        second_pending = SubscriptionRequest.objects.create(
            student=other_student,
            plan=self.annual_plan,
            reference='UNI-44444',
            amount=self.annual_plan.price,
            status=SubscriptionRequest.STATUS_PENDING,
        )
        approved = SubscriptionRequest.objects.create(
            student=approved_student,
            plan=self.semester_plan,
            reference='UNI-55555',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_APPROVED,
            activated_at=timezone.now(),
        )
        request = RequestFactory().post('/admin/accounts/subscriptionrequest/')
        request.user = get_user_model().objects.create_user(username='admin2')
        model_admin = SubscriptionRequestAdmin(SubscriptionRequest, django_admin.site)

        model_admin.reject_requests(
            request,
            SubscriptionRequest.objects.filter(id__in=[
                first_pending.id,
                second_pending.id,
                approved.id,
            ]),
        )

        first_pending.refresh_from_db()
        second_pending.refresh_from_db()
        approved.refresh_from_db()
        approved_student.refresh_from_db()
        self.assertEqual(first_pending.status, SubscriptionRequest.STATUS_REJECTED)
        self.assertEqual(second_pending.status, SubscriptionRequest.STATUS_REJECTED)
        self.assertEqual(approved.status, SubscriptionRequest.STATUS_REJECTED)
        self.assertEqual(approved_student.subscription_status, Student.SUBSCRIPTION_FREE)
        self.assertIsNone(approved_student.subscription_expiry)
        self.assertEqual(notify_rejected.call_count, 3)
        message_user.assert_called_once()

    @patch('apps.accounts.notifications.send_telegram_message')
    def test_rejected_subscription_notification_uses_plain_text_message(self, send_message):
        sub_request = SubscriptionRequest.objects.create(
            student=self.student,
            plan=self.semester_plan,
            reference='UNI-66666',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_REJECTED,
        )

        notify_subscription_rejected(sub_request)

        send_message.assert_called_once()
        chat_id, text = send_message.call_args.args
        self.assertEqual(chat_id, self.student.telegram_id)
        self.assertIn('Payment Not Verified', text)
        self.assertIn('UNI-66666', text)
        self.assertNotIn('parse_mode', send_message.call_args.kwargs)
