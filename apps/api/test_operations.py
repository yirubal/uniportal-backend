import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.auth import validate_telegram_init_data
from apps.bot.models import TelegramUpdate


@override_settings(TELEGRAM_BOT_TOKEN='123:auth-test-token')
class TelegramTimestampTests(SimpleTestCase):
    def signed(self, **fields):
        data = {'user': json.dumps({'id': 123, 'first_name': 'Student'}), **fields}
        check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
        secret = hmac.new(b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urlencode(data)

    @patch('apps.accounts.auth.time.time', return_value=1700000000)
    def test_valid_and_small_clock_skew(self, clock):
        for timestamp in ('1700000000', '1700000060', '1699913600'):
            self.assertEqual(validate_telegram_init_data(self.signed(auth_date=timestamp))['id'], 123)

    @patch('apps.accounts.auth.time.time', return_value=1700000000)
    def test_missing_malformed_old_and_future_timestamps(self, clock):
        for timestamp in (None, '', 'abc', '0', '-1', '1700000061', '1699913599', '9' * 1000):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                validate_telegram_init_data(self.signed(**({} if timestamp is None else {'auth_date': timestamp})))

    def test_duplicate_fields_and_invalid_user_are_rejected(self):
        now = str(int(timezone.now().timestamp()))
        with self.assertRaises(ValueError):
            validate_telegram_init_data(self.signed(auth_date=now) + '&auth_date=' + now)
        for user in ([], {}, {'id': True}, {'id': '123'}, {'id': 123, 'first_name': []}):
            with self.subTest(user=user), self.assertRaises(ValueError):
                validate_telegram_init_data(self.signed(auth_date=now, user=json.dumps(user)))

    def test_signature_still_required(self):
        with self.assertRaises(ValueError):
            validate_telegram_init_data(self.signed(auth_date=str(int(timezone.now().timestamp()))).replace('hash=', 'hash=wrong'))
        with self.assertRaises(ValueError):
            validate_telegram_init_data(urlencode({'auth_date': int(timezone.now().timestamp()), 'hash': 'é' * 64}))


class HealthAndRequestLogTests(TestCase):
    def test_expired_token_is_rejected_after_unverified_decode(self):
        from rest_framework_simplejwt.backends import TokenBackend
        from rest_framework_simplejwt.exceptions import TokenBackendExpiredToken
        from rest_framework_simplejwt.tokens import AccessToken
        backend = TokenBackend(algorithm='HS256', signing_key=settings.SECRET_KEY)
        expired = AccessToken()
        expired['student_id'] = 1
        expired.set_exp(from_time=timezone.now() - timedelta(days=10), lifetime=timedelta(seconds=1))
        backend.decode(str(expired), verify=False)
        with self.assertRaises(TokenBackendExpiredToken):
            backend.decode(str(expired), verify=True)

    def test_health_executes_query_and_liveness_does_not(self):
        with self.assertNumQueries(1):
            self.assertEqual(self.client.get('/health/').json()['database'], 'connected')
        with self.assertNumQueries(0):
            self.assertEqual(self.client.get('/live/').status_code, 200)

    def test_database_failure_returns_503_with_no_details(self):
        with patch('config.urls.connections') as connections:
            connections.__getitem__.return_value.cursor.side_effect = DatabaseError('private database details')
            response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.content.decode())

    def test_ids_and_logs_do_not_include_url_credentials(self):
        request_id = str(uuid4())
        with self.assertLogs('apps.api.middleware', level='INFO') as logs:
            response = self.client.get('/api/resources/1/download/file/private-signed-token/?token=secret',
                HTTP_X_REQUEST_ID=request_id, HTTP_AUTHORIZATION='Bearer private-jwt')
        self.assertEqual(response['X-Request-ID'], request_id)
        output = ' '.join(logs.output)
        for value in ('private-signed-token', 'private-jwt', 'token=secret'):
            self.assertNotIn(value, output)
        self.assertIn('route=resource-download-file', output)
        UUID(self.client.get('/live/', HTTP_X_REQUEST_ID='bad\nlog-injection')['X-Request-ID'])


@override_settings(TELEGRAM_BOT_TOKEN='123:fake', TELEGRAM_WEBHOOK_SECRET='secret', TELEGRAM_CHANNEL_ID='-100123')
class WebhookSourceTests(TestCase):
    def test_auth_rejects_non_object_body(self):
        self.assertEqual(APIClient().post('/api/auth/telegram/', [], format='json').status_code, 400)

    def test_unknown_sources_acknowledged_without_queueing(self):
        client = APIClient()
        for chat in (-100456, '-100456', None):
            response = client.post('/api/telegram/webhook/', {'update_id': 1,
                'channel_post': {'chat': {'id': chat}}}, format='json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='secret')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(TelegramUpdate.objects.count(), 0)

    def test_configured_source_and_student_updates_are_accepted(self):
        client = APIClient()
        for update_id, extra in ((1, {'channel_post': {'chat': {'id': -100123}}}), (2, {'message': {}})):
            response = client.post('/api/telegram/webhook/', {'update_id': update_id, **extra}, format='json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='secret')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(TelegramUpdate.objects.count(), 2)


class OperationalCommandTests(TestCase):
    def run_report(self, **options):
        output = StringIO()
        error = None
        try:
            call_command('check_operations', stdout=output, **options)
        except CommandError as exc:
            error = exc
        return json.loads(output.getvalue()), error

    def test_due_backlog_and_stale_claim_fail_without_mutating_work(self):
        old = timezone.now() - timedelta(hours=1)
        pending = TelegramUpdate.objects.create(update_id=1, payload={'private': 'data'}, next_attempt_at=old)
        TelegramUpdate.objects.create(update_id=2, payload={}, status='processing', claimed_at=old)
        report, error = self.run_report(disk_percent=100)
        self.assertIsNotNone(error)
        self.assertEqual(report['queues']['update']['stale'], 1)
        self.assertGreaterEqual(report['queues']['update']['overdue_seconds'], 3600)
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'pending')
        self.assertNotIn('private', json.dumps(report))

    def test_future_retry_is_not_overdue_and_backups_remain_unverified(self):
        TelegramUpdate.objects.create(update_id=1, payload={}, next_attempt_at=timezone.now() + timedelta(hours=1))
        report, error = self.run_report(disk_percent=100)
        self.assertIsNone(error)
        self.assertEqual(report['queues']['update']['overdue_seconds'], 0)
        self.assertEqual(report['backup']['status'], 'unverified')

    def test_backup_requires_both_recent_timezone_aware_timestamps(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'backups.json'
            now = timezone.now()
            path.write_text(json.dumps({'database_completed_at': now.isoformat(), 'media_completed_at': now.isoformat()}))
            report, error = self.run_report(backup_status_file=path, disk_percent=100)
            self.assertIsNone(error)
            self.assertEqual(report['backup']['status'], 'fresh')
            for data in ({'database_completed_at': now.isoformat()},
                         {'database_completed_at': (now - timedelta(days=2)).isoformat(), 'media_completed_at': now.isoformat()},
                         {'database_completed_at': (now + timedelta(days=1)).isoformat(), 'media_completed_at': now.isoformat()}):
                path.write_text(json.dumps(data))
                report, error = self.run_report(backup_status_file=path, disk_percent=100)
                self.assertIsNotNone(error)


class ProductionSettingsTests(SimpleTestCase):
    def load_settings(self, module='prod', **overrides):
        # No .env, production secrets, network or database connection is used.
        environment = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'SYSTEMROOT')}
        environment.update({'READ_DOT_ENV': 'False', 'SECRET_KEY': 'phase-six-config-test-' + 'x' * 55,
            'DEBUG': 'False', 'DATABASE_URL': 'postgresql://test:test@localhost/unused',
            'ALLOWED_HOSTS': 'api.example.test,localhost,127.0.0.1,healthcheck.railway.app',
            'TELEGRAM_BOT_TOKEN': '123:fake-config-token', 'TELEGRAM_WEBHOOK_SECRET': 'config-secret',
            'TELEGRAM_CHANNEL_ID': '-100123', 'USE_S3': 'False'})
        environment.update(overrides)
        return subprocess.run([sys.executable, '-c',
            'import importlib, json; s=importlib.import_module("config.settings.' + module + '"); '
            'print(json.dumps({"secure": s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE, '
            '"reuse": s.DATABASES["default"]["CONN_MAX_AGE"], "proxy": s.SECURE_PROXY_SSL_HEADER, '
            '"handlers": s.LOGGING["root"]["handlers"]}))'],
            cwd=settings.BASE_DIR, env=environment, capture_output=True, text=True, timeout=20)

    def test_prod_and_docker_share_secure_defaults(self):
        for module in ('prod', 'docker'):
            result = self.load_settings(module)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'secure': True, 'reuse': 60, 'proxy': None, 'handlers': ['console']})

    def test_missing_required_config_and_development_key_fail_closed(self):
        for field, value in (('SECRET_KEY', 'django-insecure-' + 'x' * 60), ('TELEGRAM_BOT_TOKEN', ''),
                ('TELEGRAM_WEBHOOK_SECRET', ''), ('TELEGRAM_WEBHOOK_SECRET', 'bad secret'),
                ('TELEGRAM_CHANNEL_ID', ''), ('TELEGRAM_CHANNEL_ID', 'not-a-chat'), ('ALLOWED_HOSTS', '*'),
                ('DATABASE_URL', 'sqlite:///:memory:'), ('DEBUG', 'True')):
            with self.subTest(field=field):
                result = self.load_settings(**{field: value})
                self.assertNotEqual(result.returncode, 0)

    def test_proxy_trust_is_explicit_and_local_debug_remains_available(self):
        result = self.load_settings(TRUST_PROXY_HTTPS='True')
        self.assertEqual(json.loads(result.stdout)['proxy'], ['HTTP_X_FORWARDED_PROTO', 'https'])
        result = self.load_settings('docker', DEBUG='True', TELEGRAM_BOT_TOKEN='', TELEGRAM_WEBHOOK_SECRET='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['secure'])
