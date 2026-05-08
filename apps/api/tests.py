from unittest.mock import patch
import shutil
import tempfile
from datetime import timedelta
from urllib.parse import urlsplit

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.admin import SubscriptionRequestAdmin
from apps.accounts.notifications import (
    notify_subscription_rejected,
    notify_subscription_request_created,
)
from apps.accounts.models import SiteSettings, Student, SubscriptionPlan, SubscriptionRequest
from apps.api.views import RESOURCE_DOWNLOAD_TOKEN_MAX_AGE, _generate_jwt
from apps.content.models import Course, Resource


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
        self.site_settings = SiteSettings.get()
        self.site_settings.telebirr_number = '0911223344'
        self.site_settings.telebirr_name = 'Unity Telebirr'
        self.site_settings.cbe_account = '1000123456789'
        self.site_settings.cbe_name = 'Unity CBE'
        self.site_settings.save()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_generate_jwt(self.student)}')

    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_creates_request_once_and_notifies_after_save(self, notify_created):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/subscription/request/',
                {
                    'plan': self.semester_plan.plan_id,
                    'payment_method': SubscriptionRequest.PAYMENT_TELEBIRR,
                    'payment_reference': 'TB123ABC',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SubscriptionRequest.objects.count(), 1)
        sub_request = SubscriptionRequest.objects.get()
        self.assertEqual(response.data['reference'], sub_request.reference)
        self.assertEqual(response.data['status'], SubscriptionRequest.STATUS_PENDING)
        self.assertEqual(sub_request.payment_reference, 'TB123ABC')
        self.assertEqual(response.data['payment_reference'], 'TB123ABC')
        self.assertEqual(response.data['payment_destination']['label'], 'Telebirr number')
        self.assertEqual(response.data['payment_destination']['value'], '0911223344')
        self.assertEqual(response.data['payment_destination']['name'], 'Unity Telebirr')
        self.assertEqual(response.data['payment_options']['telebirr']['number'], '0911223344')
        self.assertEqual(response.data['payment_options']['telebirr']['name'], 'Unity Telebirr')
        self.assertEqual(response.data['payment_options']['cbe']['account'], '1000123456789')
        self.assertEqual(response.data['payment_options']['cbe']['name'], 'Unity CBE')
        notify_created.assert_called_once_with(sub_request)

    @patch('apps.bot.notifications.send_admin_notification')
    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_notifies_admin_after_subscription_request_is_created(
        self,
        notify_created,
        send_admin_notification,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/subscription/request/',
                {
                    'plan': self.semester_plan.plan_id,
                    'payment_method': SubscriptionRequest.PAYMENT_TELEBIRR,
                    'payment_reference': 'TB77ADMIN',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        sub_request = SubscriptionRequest.objects.get()
        notify_created.assert_called_once_with(sub_request)
        send_admin_notification.assert_called_once()
        message = send_admin_notification.call_args.args[0]
        self.assertIn('New Subscription Request', message)
        self.assertIn('Test', message)
        self.assertIn(self.semester_plan.name, message)
        self.assertIn('TB77ADMIN', message)
        self.assertIn(sub_request.reference, message)

    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_accepts_cbe_transaction_id_and_returns_cbe_destination(self, notify_created):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/subscription/request/',
                {
                    'plan': self.semester_plan.plan_id,
                    'payment_method': SubscriptionRequest.PAYMENT_CBE,
                    'payment_reference': 'CBE42FT9A',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        sub_request = SubscriptionRequest.objects.get()
        self.assertEqual(sub_request.payment_method, SubscriptionRequest.PAYMENT_CBE)
        self.assertEqual(sub_request.payment_reference, 'CBE42FT9A')
        self.assertEqual(response.data['payment_destination']['label'], 'CBE account number')
        self.assertEqual(response.data['payment_destination']['value'], '1000123456789')
        self.assertEqual(response.data['payment_destination']['name'], 'Unity CBE')
        self.assertEqual(response.data['payment_options']['telebirr']['number'], '0911223344')
        self.assertEqual(response.data['payment_options']['telebirr']['name'], 'Unity Telebirr')
        self.assertEqual(response.data['payment_options']['cbe']['account'], '1000123456789')
        self.assertEqual(response.data['payment_options']['cbe']['name'], 'Unity CBE')
        notify_created.assert_called_once_with(sub_request)

    def test_post_rejects_invalid_transaction_reference(self):
        response = self.client.post(
            '/api/subscription/request/',
            {
                'plan': self.semester_plan.plan_id,
                'payment_method': SubscriptionRequest.PAYMENT_TELEBIRR,
                'payment_reference': '0911000000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'INVALID_PAYMENT_REFERENCE')
        self.assertEqual(SubscriptionRequest.objects.count(), 0)

    @patch('apps.accounts.notifications.notify_subscription_request_created')
    def test_post_returns_existing_pending_request_instead_of_duplicate(self, notify_created):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(
                '/api/subscription/request/',
                {'plan': self.semester_plan.plan_id, 'payment_reference': 'TB123ABC'},
                format='json',
            )
        with self.captureOnCommitCallbacks(execute=True):
            second = self.client.post(
                '/api/subscription/request/',
                {'plan': self.annual_plan.plan_id, 'payment_reference': 'TB999XYZ'},
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
        self.assertEqual(response.data['payment_options']['telebirr']['number'], '0911223344')
        self.assertEqual(response.data['payment_options']['telebirr']['name'], 'Unity Telebirr')
        self.assertEqual(response.data['payment_options']['cbe']['account'], '1000123456789')
        self.assertEqual(response.data['payment_options']['cbe']['name'], 'Unity CBE')

    def test_student_profile_reports_free_when_premium_status_has_no_valid_expiry(self):
        self.student.subscription_status = Student.SUBSCRIPTION_PREMIUM
        self.student.subscription_expiry = None
        self.student.save(update_fields=['subscription_status', 'subscription_expiry'])

        response = self.client.get('/api/students/me/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_premium'])
        self.assertEqual(response.data['subscription_status'], Student.SUBSCRIPTION_FREE)

    @patch('apps.accounts.admin.notify_subscription_approved')
    @patch('apps.accounts.admin.SubscriptionRequestAdmin.message_user')
    def test_admin_approval_updates_student_premium_status_for_profile(self, message_user, notify_approved):
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

        request = RequestFactory().post('/admin/accounts/subscriptionrequest/')
        request.user = admin_user
        model_admin = SubscriptionRequestAdmin(SubscriptionRequest, django_admin.site)
        model_admin.approve_requests(
            request,
            SubscriptionRequest.objects.filter(id=sub_request.id),
        )
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
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
            subscription_expiry=timezone.now() + timedelta(days=self.semester_plan.days),
        )
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
    def test_under_review_notification_uses_plain_text_message(self, send_message):
        sub_request = SubscriptionRequest.objects.create(
            student=self.student,
            plan=self.semester_plan,
            reference='UNI-00001',
            amount=self.semester_plan.price,
            status=SubscriptionRequest.STATUS_PENDING,
        )

        notify_subscription_request_created(sub_request)

        send_message.assert_called_once()
        chat_id, text = send_message.call_args.args
        self.assertEqual(chat_id, self.student.telegram_id)
        self.assertIn('Payment Request Under Review', text)
        self.assertIn('UNI-00001', text)
        self.assertIn(self.semester_plan.name, text)
        self.assertNotIn('parse_mode', send_message.call_args.kwargs)

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


@override_settings(TELEGRAM_BOT_TOKEN='test-token')
class ResourceDownloadTests(APITestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()

        self.student = Student.objects.create(
            telegram_id=1234567,
            first_name='Premium',
            username='premiumuser',
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
            subscription_expiry=timezone.now() + timedelta(days=10),
        )
        self.free_student = Student.objects.create(
            telegram_id=7654321,
            first_name='Free',
            username='freeuser',
        )
        self.course = Course.objects.create(
            name='Introduction to Accounting',
            code='ACCT101',
        )
        self.resource = Resource.objects.create(
            title='Lecture Pack',
            file=SimpleUploadedFile(
                'lecture-pack.pdf',
                b'%PDF-1.4 test file',
                content_type='application/pdf',
            ),
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
        )
        self.resource.courses.add(self.course)

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def authenticate(self, student):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_generate_jwt(student)}')

    def test_post_returns_signed_download_url_that_streams_without_auth_headers(self):
        self.authenticate(self.student)

        response = self.client.post(f'/api/resources/{self.resource.id}/download/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['filename'], 'lecture-pack.pdf')
        self.assertEqual(response.data['expires_in'], RESOURCE_DOWNLOAD_TOKEN_MAX_AGE)
        self.assertIn(
            f'/api/resources/{self.resource.id}/download/file/',
            response.data['url'],
        )
        self.assertNotIn('?token=', response.data['url'])

        self.resource.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.resource.downloads_count, 1)
        self.assertEqual(self.student.downloads_today, 1)

        self.client.credentials()
        signed_url = urlsplit(response.data['url'])
        download_response = self.client.get(f'{signed_url.path}?{signed_url.query}')

        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            b''.join(download_response.streaming_content),
            b'%PDF-1.4 test file',
        )
        self.assertEqual(download_response['Content-Type'], 'application/pdf')
        self.assertIn(
            'attachment; filename="lecture-pack.pdf"',
            download_response['Content-Disposition'],
        )

        head_response = self.client.head(f'{signed_url.path}?{signed_url.query}')
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response['Content-Type'], 'application/pdf')
        self.assertIn(
            'attachment; filename="lecture-pack.pdf"',
            head_response['Content-Disposition'],
        )

    def test_query_token_download_still_streams_for_existing_links(self):
        self.authenticate(self.student)

        response = self.client.post(f'/api/resources/{self.resource.id}/download/')
        signed_url = urlsplit(response.data['url'])
        token = signed_url.path.rstrip('/').rsplit('/', 1)[-1]

        self.client.credentials()
        download_response = self.client.get(
            f'/api/resources/{self.resource.id}/download/file/?token={token}'
        )

        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            b''.join(download_response.streaming_content),
            b'%PDF-1.4 test file',
        )

    def test_free_student_cannot_prepare_premium_resource_download(self):
        self.authenticate(self.free_student)

        response = self.client.post(f'/api/resources/{self.resource.id}/download/')

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.data['upgrade_required'])

        self.resource.refresh_from_db()
        self.free_student.refresh_from_db()
        self.assertEqual(self.resource.downloads_count, 0)
        self.assertEqual(self.free_student.downloads_today, 0)
