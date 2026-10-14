"""Verify download accounting under concurrent PostgreSQL requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Student
from apps.content.models import Resource
from .views import _generate_jwt


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentDownloadTests(TransactionTestCase):
    def test_concurrent_links_reset_daily_count_once_without_losing_increments(self):
        student = Student.objects.create(telegram_id=123459, first_name='Concurrent Download')
        Student.objects.filter(pk=student.pk).update(
            downloads_today=10, last_download_reset=timezone.localdate() - timedelta(days=1),
        )
        resource = Resource.objects.create(
            title='Concurrent Resource', file='resources/concurrent.pdf',
            access_level=Resource.ACCESS_FREE, status=Resource.STATUS_PUBLISHED,
        )
        token = _generate_jwt(student)
        barrier = Barrier(2)

        def issue_link():
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
                barrier.wait(timeout=10)
                return client.post(f'/api/resources/{resource.pk}/download/').status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(issue_link) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results, [200, 200])
        student.refresh_from_db()
        resource.refresh_from_db()
        self.assertEqual(student.downloads_today, 2)
        self.assertEqual(student.last_download_reset, timezone.localdate())
        self.assertEqual(resource.downloads_count, 2)
