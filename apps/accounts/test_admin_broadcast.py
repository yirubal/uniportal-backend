from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.bot.models import NotificationDelivery
from apps.bot.worker import refresh_broadcast
from .models import BroadcastMessage, Student
from .notifications import queue_broadcast


@override_settings(ALLOWED_HOSTS=['testserver'])
class BroadcastAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('broadcast-editor')
        self.client.force_login(self.user)
        Student.objects.create(telegram_id=1, first_name='Active')
        Student.objects.create(telegram_id=2, first_name='Also active')
        Student.objects.create(telegram_id=3, first_name='Inactive', is_active=False)
        self.url = reverse('admin:accounts_broadcast')

    def token(self):
        return self.client.get(self.url).context['form']['submission_token'].value()

    def send(self, token, **values):
        return self.client.post(self.url, {'submission_token': token, 'message': 'Hello students', 'parse_mode': '', **values})

    def test_repeated_submission_queues_one_broadcast_and_one_delivery_per_active_student(self):
        token = self.token()
        self.assertEqual(self.send(token).status_code, 302)
        self.assertEqual(self.send(token).status_code, 302)
        self.assertEqual(BroadcastMessage.objects.count(), 1)
        self.assertEqual(NotificationDelivery.objects.count(), 2)
        self.assertEqual(BroadcastMessage.objects.get().total_users, 2)

    def test_confirmation_cannot_be_reused_with_changed_message(self):
        token = self.token()
        self.send(token)
        response = self.send(token, message='Another message')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(BroadcastMessage.objects.count(), 1)

    def test_invalid_input_preserves_message_and_formatting_without_queueing(self):
        response = self.send(self.token(), parse_mode='Unsupported', message='Keep this draft')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Keep this draft')
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(BroadcastMessage.objects.count(), 0)

    def test_unsigned_or_other_user_confirmation_cannot_send(self):
        token = self.token()
        self.assertEqual(self.send('invalid').status_code, 200)
        other = get_user_model().objects.create_superuser('another-broadcast-editor')
        self.client.force_login(other)
        self.assertEqual(self.send(token).status_code, 200)
        self.assertEqual(BroadcastMessage.objects.count(), 0)

    def test_progress_and_failure_link_match_saved_delivery_results(self):
        self.send(self.token())
        broadcast = BroadcastMessage.objects.get()
        deliveries = list(NotificationDelivery.objects.filter(broadcast=broadcast).order_by('pk'))
        NotificationDelivery.objects.filter(pk=deliveries[0].pk).update(status='processed')
        NotificationDelivery.objects.filter(pk=deliveries[1].pk).update(status='failed')
        refresh_broadcast(broadcast.pk)
        response = self.client.get(reverse('admin:accounts_broadcast_status'))
        self.assertEqual(response.json()['broadcasts'][0], {
            'id': broadcast.pk, 'total': 2, 'delivered': 1, 'pending': 0, 'failed': 1,
        })
        response = self.client.get(self.url)
        self.assertContains(response, 'Review failed deliveries')
        self.assertContains(response, f'broadcast__id__exact={broadcast.pk}&amp;attention=failed')
        self.assertNotContains(response, '{{ b.sent_at')
        self.assertContains(response, '2 currently active students')

    def test_compose_only_staff_can_see_only_their_own_history(self):
        queue_broadcast('Private other history', sent_by=self.user)
        user = get_user_model().objects.create_user('compose-only', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='add_broadcastmessage'))
        self.client.force_login(user)
        self.assertNotContains(self.client.get(self.url), 'Private other history')
        self.assertEqual(self.client.get(reverse('admin:accounts_broadcast_status')).json()['broadcasts'], [])
        self.send(self.token(), message='My own broadcast')
        self.assertContains(self.client.get(self.url), 'My own broadcast')

    def test_status_denies_staff_without_broadcast_permissions(self):
        user = get_user_model().objects.create_user('no-broadcast', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin:accounts_broadcast_status')).status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL concurrent transactions')
class ConcurrentBroadcastTests(TransactionTestCase):
    def test_concurrent_confirmation_creates_only_one_broadcast(self):
        user = get_user_model().objects.create_user('concurrent-sender')
        Student.objects.create(telegram_id=12345)
        token, barrier = uuid4(), Barrier(2)

        def send():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return queue_broadcast('One broadcast', sent_by=user, submission_token=token).pk
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(BroadcastMessage.objects.count(), 1)
        self.assertEqual(NotificationDelivery.objects.count(), 1)
