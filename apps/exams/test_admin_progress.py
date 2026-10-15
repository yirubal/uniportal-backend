from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ExamPDFUpload, ExamTerm


@override_settings(ALLOWED_HOSTS=['testserver'])
class ExamAdminProgressTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('progress-admin')
        self.client.force_login(self.user)
        self.term = ExamTerm.objects.create(year=2018, term=1)
        self.upload = ExamPDFUpload.objects.create(original_name='Attendance.pdf', pdf_type='attendance', term=self.term)

    def test_global_and_term_status_refresh_counts_and_terminal_results(self):
        global_url = reverse('admin:exams_examterm_upload_status')
        term_url = reverse('admin:exam_upload_status', args=[self.term.pk])
        for url in [global_url, term_url]:
            data = self.client.get(url, {'details': '1'}).json()
            self.assertEqual(data['pending'], 1)
            self.assertEqual(data['uploads'][0]['status'], 'pending')
        ExamPDFUpload.objects.filter(pk=self.upload.pk).update(status='failed', error_message='<b>Parser failure</b>')
        for url in [global_url, term_url]:
            data = self.client.get(url, {'details': '1'}).json()
            self.assertEqual(data['failed'], 1)
            self.assertEqual(data['pending'], 0)
            self.assertEqual(data['uploads'][0]['error_message'], '<b>Parser failure</b>')
            self.assertEqual(data['uploads'][0]['url'], reverse('admin:exams_exampdfupload_change', args=[self.upload.pk]))

    def test_term_scope_excludes_other_terms_and_rows_are_bounded(self):
        ExamPDFUpload.objects.bulk_create([ExamPDFUpload(original_name=f'file-{i}', pdf_type='schedule') for i in range(55)])
        data = self.client.get(reverse('admin:exams_examterm_upload_status'), {'details': '1'}).json()
        self.assertEqual(data['pending'], 56)
        self.assertEqual(len(data['uploads']), 50)
        data = self.client.get(reverse('admin:exam_upload_status', args=[self.term.pk]), {'details': '1'}).json()
        self.assertEqual(data['pending'], 1)
        self.assertEqual(len(data['uploads']), 1)

    def test_view_only_staff_can_read_status_but_cannot_upload(self):
        user = get_user_model().objects.create_user('status-reader', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='view_exampdfupload'))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin:exams_examterm_upload_status')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:exams_examterm_upload_pdfs')).status_code, 403)

    def test_upload_screens_have_refresh_and_recovery_without_manual_process_button(self):
        for url in [reverse('admin:exams_examterm_upload_pdfs'), reverse('admin:exam_upload_pdfs', args=[self.term.pk])]:
            response = self.client.get(url)
            self.assertContains(response, 'Refresh status')
            self.assertContains(response, 'Open all imports and retry controls')
            self.assertContains(response, 'details=1')
            self.assertNotContains(response, 'process-btn')
