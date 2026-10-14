from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from rest_framework.test import APIClient

from .models import TelegramUpdate
from .worker import claim_work


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentWorkTests(TransactionTestCase):
    def test_competing_claims_have_one_owner(self):
        record = TelegramUpdate.objects.create(update_id=8000, payload={'update_id': 8000})
        barrier = Barrier(2)

        def claim():
            try:
                barrier.wait(timeout=10)
                return claim_work('update')
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        owners = [result for result in results if result]
        self.assertEqual(len(owners), 1)
        record.refresh_from_db()
        self.assertEqual(record.claim_token, owners[0][1])
        self.assertEqual(record.attempt_count, 1)

    @override_settings(TELEGRAM_BOT_TOKEN='test', TELEGRAM_WEBHOOK_SECRET='')
    def test_duplicate_webhooks_create_one_durable_update(self):
        barrier = Barrier(2)

        def accept():
            try:
                barrier.wait(timeout=10)
                return APIClient().post('/api/telegram/webhook/', {'update_id': 8001}, format='json').status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(accept) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results, [200, 200])
        self.assertEqual(TelegramUpdate.objects.filter(update_id=8001).count(), 1)
