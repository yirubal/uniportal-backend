from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .admin import SubscriptionRequestAdmin
from .models import Student, SubscriptionPlan, SubscriptionRequest
from .services import approve_subscription_request, reject_subscription_request


class PaymentCorrectnessTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(telegram_id=600001, first_name='Payment Test')
        self.plan = SubscriptionPlan.objects.create(plan_id='semester', name='Semester', price=500, days=30)
        self.request = SubscriptionRequest.objects.create(
            student=self.student, plan=self.plan, amount=self.plan.price, reference='UNI-COR01',
        )
        self.admin_user = get_user_model().objects.create_user(username='payment-admin')

    @patch('apps.accounts.services.notify_subscription_approved')
    def test_approval_extends_existing_expiry_once_and_notifies_after_commit(self, notify):
        expiry = timezone.now() + timedelta(days=10)
        self.student.subscription_status = 'premium'
        self.student.subscription_expiry = expiry
        self.student.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(approve_subscription_request(self.request.pk, self.admin_user))
            self.assertFalse(approve_subscription_request(self.request.pk, self.admin_user))
            notify.assert_not_called()
        self.student.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.student.subscription_expiry, expiry + timedelta(days=30))
        self.assertEqual(self.request.activated_by, self.admin_user)
        notify.assert_called_once()

    @patch('apps.accounts.services.notify_subscription_approved')
    def test_failed_approval_rolls_back_student_and_request(self, notify):
        with self.captureOnCommitCallbacks(execute=True):
            with patch.object(SubscriptionRequest, 'save', side_effect=RuntimeError('Failed save')):
                with self.assertRaises(RuntimeError):
                    approve_subscription_request(self.request.pk, self.admin_user)
        self.student.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.student.subscription_status, 'free')
        self.assertIsNone(self.student.subscription_expiry)
        self.assertEqual(self.request.status, 'pending')
        notify.assert_not_called()

    @patch('apps.accounts.services.notify_subscription_approved', side_effect=RuntimeError('Telegram unavailable'))
    def test_notification_failure_does_not_undo_approval(self, notify):
        with self.assertLogs('django', level='ERROR'):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(approve_subscription_request(self.request.pk, self.admin_user))
        self.request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.request.status, 'approved')
        self.assertTrue(self.student.is_premium)

    @patch('apps.accounts.services.notify_subscription_rejected')
    def test_pending_rejection_is_once_only_and_notifies_after_commit(self, notify):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(reject_subscription_request(self.request.pk))
            self.assertFalse(reject_subscription_request(self.request.pk))
            notify.assert_not_called()
        self.request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.request.status, 'rejected')
        self.assertEqual(self.student.subscription_status, 'free')
        notify.assert_called_once()

    @patch('apps.accounts.services.notify_subscription_approved')
    @patch('apps.accounts.services.notify_subscription_rejected')
    def test_approved_request_and_renewal_cannot_be_rejected(self, notify_rejected, notify_approved):
        with self.captureOnCommitCallbacks(execute=True):
            approve_subscription_request(self.request.pk, self.admin_user)
            renewal = SubscriptionRequest.objects.create(
                student=self.student, plan=self.plan, amount=self.plan.price, reference='UNI-COR02',
            )
            approve_subscription_request(renewal.pk, self.admin_user)
            self.student.refresh_from_db()
            expiry = self.student.subscription_expiry
            self.assertFalse(reject_subscription_request(self.request.pk))
            self.assertFalse(reject_subscription_request(renewal.pk))
        self.student.refresh_from_db()
        self.assertEqual(self.student.subscription_expiry, expiry)
        self.assertEqual(SubscriptionRequest.objects.filter(status='approved').count(), 2)
        notify_rejected.assert_not_called()

    @patch('apps.accounts.services.notify_subscription_approved')
    def test_admin_detail_cannot_reject_an_approved_payment(self, notify):
        with self.captureOnCommitCallbacks(execute=True):
            approve_subscription_request(self.request.pk, self.admin_user)
        self.request.refresh_from_db()
        self.request.status = 'rejected'
        request = RequestFactory().post('/admin/accounts/subscriptionrequest/')
        request.user = self.admin_user
        model_admin = SubscriptionRequestAdmin(SubscriptionRequest, admin.site)
        with patch.object(model_admin, 'message_user'):
            model_admin.save_model(request, self.request, form=None, change=True)
        self.request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.request.status, 'approved')
        self.assertTrue(self.student.is_premium)
