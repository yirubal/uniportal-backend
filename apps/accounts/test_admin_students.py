from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Student


class StudentAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser('student-admin'))
        self.student = Student.objects.create(telegram_id=991234, first_name='Student', username='training-user')
        self.url = reverse('admin:accounts_student_change', args=[self.student.pk])

    def test_student_change_page_opens_from_filtered_search(self):
        response = self.client.get(self.url, {'_changelist_filters': 'q=training-user'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('last_download_reset', response.context['adminform'].form.fields)
        self.assertContains(response, 'Last download reset')

    def test_student_edits_preserve_system_managed_reset_and_subscription_fields(self):
        reset_date = self.student.last_download_reset
        response = self.client.post(self.url, {
            'first_name': 'Updated student', 'last_name': '', 'username': 'training-user',
            'downloads_today': '3', 'is_active': 'on',
            'last_download_reset': '2099-01-01', 'subscription_status': 'premium',
            'subscription_expiry': '2099-01-01 00:00:00',
        })
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Updated student')
        self.assertEqual(self.student.downloads_today, 3)
        self.assertEqual(self.student.last_download_reset, reset_date)
        self.assertEqual(self.student.subscription_status, Student.SUBSCRIPTION_FREE)
        self.assertIsNone(self.student.subscription_expiry)
