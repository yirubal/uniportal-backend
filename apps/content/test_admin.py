from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.bot.models import NotificationDelivery, QuestionExtraction, TelegramUpdate
from apps.content.admin import FileInboxAdmin
from apps.content.models import Course, FileInbox, Resource
from apps.exams.models import ExamPDFUpload, ExamTerm
from apps.quiz.models import ExamPaper


@override_settings(ALLOWED_HOSTS=['testserver'])
class AdminSafetyTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('restricted', is_staff=True)
        self.client.force_login(self.staff)
        self.course = Course.objects.create(name='Audit course', code='AUDIT')
        self.resource = Resource.objects.create(title='Module', file_type='module')
        self.resource.courses.add(self.course)
        self.term = ExamTerm.objects.create(year=2018, term=1)
        self.paper = ExamPaper.objects.create(title='Audit paper', exam_type='final', year=2018)

    def grant(self, *permissions):
        for permission in permissions:
            app, codename = permission.split('.')
            self.staff.user_permissions.add(Permission.objects.get(
                content_type__app_label=app, codename=codename,
            ))

    def test_custom_routes_deny_staff_without_model_permissions(self):
        paths = [
            reverse('admin:course_resource_audit'),
            reverse('admin:course_resource_detail', args=[self.course.pk]),
            reverse('admin:accounts_broadcast'),
            reverse('admin:exams_examterm_upload_pdfs'),
            reverse('admin:exam_upload_pdfs', args=[self.term.pk]),
            reverse('admin:exam_upload_status', args=[self.term.pk]),
            reverse('admin:quiz_question_bulk_metadata'),
            reverse('admin:quiz_exampaper_import_questions', args=[self.paper.pk]),
            reverse('admin:quiz_exampaper_download_template'),
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
                self.assertEqual(self.client.post(path, {}).status_code, 403)

    def test_unauthorized_delete_and_activation_do_not_mutate_records(self):
        for name, pk in [
            ('admin:delete_resource', self.resource.pk),
            ('admin:delete_duplicate_resources', self.course.pk),
            ('admin:exams_examterm_activate', self.term.pk),
            ('admin:exams_examterm_deactivate', self.term.pk),
        ]:
            self.assertEqual(self.client.post(reverse(name, args=[pk])).status_code, 403)
        self.assertTrue(Resource.objects.filter(pk=self.resource.pk).exists())
        self.term.refresh_from_db()
        self.assertFalse(self.term.is_active)

    def test_audit_requires_both_permissions_and_hides_delete_and_add_controls(self):
        self.grant('content.view_course')
        url = reverse('admin:course_resource_detail', args=[self.course.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant('content.view_resource')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Review deletion')
        self.assertNotContains(response, '+ Add Resource')
        self.assertNotContains(response, 'Delete All Duplicates')

    def test_legacy_delete_requires_standard_confirmation_and_logs_deletion(self):
        self.grant('content.delete_resource', 'content.view_resource')
        legacy = reverse('admin:delete_resource', args=[self.resource.pk])
        standard = reverse('admin:content_resource_delete', args=[self.resource.pk])
        self.assertEqual(self.client.get(legacy).status_code, 405)
        self.assertRedirects(self.client.post(legacy), standard)
        self.assertTrue(Resource.objects.filter(pk=self.resource.pk).exists())
        self.assertEqual(self.client.post(standard, {'post': 'yes'}).status_code, 302)
        self.assertFalse(Resource.objects.filter(pk=self.resource.pk).exists())
        self.assertTrue(LogEntry.objects.filter(
            object_id=str(self.resource.pk), action_flag=DELETION, user=self.staff,
        ).exists())

    def test_title_duplicate_cleanup_preserves_different_and_shared_resources(self):
        self.grant('content.view_course', 'content.view_resource')
        other = Course.objects.create(name='Other course', code='OTHER')
        duplicate = Resource.objects.create(title='Module', file_type='worksheet')
        duplicate.courses.add(self.course, other)
        response = self.client.post(reverse('admin:delete_duplicate_resources', args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Resource.objects.count(), 2)
        self.assertTrue(duplicate.courses.filter(pk=other.pk).exists())

    def test_authorized_upload_and_broadcast_pages_remain_available(self):
        self.grant('accounts.add_broadcastmessage', 'exams.add_exampdfupload', 'exams.view_exampdfupload')
        self.assertEqual(self.client.get(reverse('admin:accounts_broadcast')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:exams_examterm_upload_pdfs')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:exam_upload_status', args=[self.term.pk])).status_code, 200)

    def test_question_import_requires_question_add_permission(self):
        self.grant('quiz.change_exampaper')
        url = reverse('admin:quiz_exampaper_import_questions', args=[self.paper.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant('quiz.add_question')
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_view_only_staff_cannot_invoke_mutating_admin_actions(self):
        self.grant('content.view_fileinbox', 'exams.view_exampdfupload', 'bot.view_notificationdelivery')
        for model, action in [
            (FileInbox, 'retry_failed_extraction'),
            (ExamPDFUpload, 'retry_failed_uploads'),
            (NotificationDelivery, 'retry_failed'),
        ]:
            request = RequestFactory().get('/')
            request.user = get_user_model().objects.get(pk=self.staff.pk)
            self.assertNotIn(action, admin.site._registry[model].get_actions(request))

    def test_job_history_cannot_be_deleted_even_by_superuser(self):
        request = RequestFactory().get('/')
        request.user = get_user_model().objects.create_superuser('root')
        for model in [TelegramUpdate, NotificationDelivery, QuestionExtraction, ExamPDFUpload]:
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_delete_permission(request))
            self.assertNotIn('delete_selected', model_admin.get_actions(request))

    def test_view_only_term_page_hides_activation_controls(self):
        self.grant('exams.view_examterm')
        response = self.client.get(reverse('admin:exams_examterm_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'formaction=')
        self.assertNotContains(response, 'Upload Exam PDFs')


class InboxRecoveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('recovery')
        self.request = RequestFactory().post('/')
        self.request.user = self.user
        self.model_admin = FileInboxAdmin(FileInbox, admin.site)

    def inbox(self, message_id, **values):
        return FileInbox.objects.create(
            original_filename='module.pdf', telegram_message_id=message_id,
            posted_date=timezone.now(), **values,
        )

    @patch.object(FileInboxAdmin, 'message_user')
    def test_retry_resets_only_failed_unassigned_files_with_storage_references(self, message):
        failed = self.inbox(1, file='inbox/module.pdf', processing_status='failed',
                            attempt_count=5, processing_error='Failed extraction',
                            claimed_at=timezone.now(), claim_token=uuid4(),
                            next_attempt_at=timezone.now() + timedelta(hours=1))
        missing = self.inbox(2, processing_status='failed')
        resource = Resource.objects.create(title='Existing', file_type='module')
        assigned = self.inbox(3, file='inbox/assigned.pdf', processing_status='failed', assigned_resource=resource)
        running = self.inbox(4, file='inbox/running.pdf', processing_status='processing')
        self.assertIn('retry_failed_extraction', self.model_admin.get_actions(self.request))
        self.model_admin.retry_failed_extraction(self.request, FileInbox.objects.all())
        failed.refresh_from_db()
        self.assertEqual(failed.processing_status, 'unprocessed')
        self.assertEqual(failed.attempt_count, 0)
        self.assertEqual(failed.processing_error, '')
        self.assertIsNone(failed.claimed_at)
        self.assertIsNone(failed.claim_token)
        self.assertLessEqual(failed.next_attempt_at, timezone.now())
        for obj, expected in [(missing, 'failed'), (assigned, 'failed'), (running, 'processing')]:
            obj.refresh_from_db()
            self.assertEqual(obj.processing_status, expected)
        self.assertIn('3 ineligible', message.call_args.args[1])

    def test_draft_creation_requires_resource_add_as_well_as_inbox_change(self):
        user = get_user_model().objects.create_user('inbox-only', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='change_fileinbox'))
        self.request.user = user
        self.assertNotIn('publish_as_resource', self.model_admin.get_actions(self.request))
