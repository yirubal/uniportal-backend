import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .extractor import GeminiQuotaExceeded
from .models import QuestionExtraction
from .test_generation import rows

EXTRACTED = [{'question_type': 'mcq', 'correct_option': 'a', 'option_a': 'Fourteen days'}]


@override_settings(GEMINI_API_KEY='test-secret-never-output', GEMINI_MODEL='configured-test-model')
class AIReadinessTests(SimpleTestCase):
    def run_check(self, *args, fails=False):
        output = StringIO()
        if fails:
            with self.assertRaises(CommandError):
                call_command('check_ai', *args, stdout=output)
        else:
            call_command('check_ai', *args, stdout=output)
        self.assertNotIn('test-secret-never-output', output.getvalue())
        return json.loads(output.getvalue())

    def test_default_checks_configuration_without_database_or_provider(self):
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk') as provider:
            result = self.run_check()
        provider.assert_not_called()
        self.assertTrue(result['healthy'])
        self.assertEqual(result['provider'], 'not_tested')
        self.assertEqual(result['database'], 'not_checked')

    @override_settings(GEMINI_API_KEY='')
    def test_missing_key_stops_before_any_probe(self):
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk') as provider:
            result = self.run_check('--probe', fails=True)
        provider.assert_not_called()
        self.assertFalse(result['key_configured'])
        self.assertEqual(result['provider_requests_attempted'], 0)

    def test_probe_calls_extraction_and_generation_once_with_synthetic_material(self):
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk', return_value=EXTRACTED) as extract, \
             patch('apps.bot.management.commands.check_ai._generate_batch', return_value=rows()) as generate:
            result = self.run_check('--probe')
        extract.assert_called_once()
        generate.assert_called_once()
        self.assertIn('Synthetic verification exam', extract.call_args.args[1])
        self.assertIn('fictional library', generate.call_args.args[0].source_text)
        self.assertEqual(result['provider_requests_attempted'], 2)
        self.assertEqual(result['provider'], 'passed')

    def test_bad_extraction_stops_without_generation(self):
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk', return_value=[]), \
             patch('apps.bot.management.commands.check_ai._generate_batch') as generate:
            result = self.run_check('--probe', fails=True)
        generate.assert_not_called()
        self.assertEqual(result['provider'], 'request_or_validation_failed')
        self.assertEqual(result['provider_requests_attempted'], 1)

    def test_quota_is_reported_without_retry_or_raw_provider_details(self):
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk', side_effect=GeminiQuotaExceeded('test-secret-never-output')) as provider:
            result = self.run_check('--probe', fails=True)
        provider.assert_called_once()
        self.assertEqual(result['provider'], 'quota_reached')

    def test_generation_failure_is_sanitized_and_does_not_retry(self):
        for error, status in [(ValueError('test-secret-never-output'), 'request_or_validation_failed'),
                              (RuntimeError('test-secret-never-output'), 'provider_unavailable')]:
            with self.subTest(error=type(error).__name__), \
                 patch('apps.bot.management.commands.check_ai._extract_from_chunk', return_value=EXTRACTED), \
                 patch('apps.bot.management.commands.check_ai._generate_batch', side_effect=error) as generate:
                result = self.run_check('--probe', fails=True)
                generate.assert_called_once()
                self.assertEqual(result['provider'], status)
                self.assertEqual(result['provider_requests_attempted'], 2)


@override_settings(GEMINI_API_KEY='test-key')
class AIDatabaseReadinessTests(TestCase):
    def run_check(self, fails=False, probe=False):
        output = StringIO()
        args = ['--database', *(['--probe'] if probe else [])]
        if fails:
            with self.assertRaises(CommandError):
                call_command('check_ai', *args, stdout=output)
        else:
            call_command('check_ai', *args, stdout=output)
        return json.loads(output.getvalue())

    def test_database_readiness_reports_counts_without_changing_records(self):
        QuestionExtraction.objects.create(source_hash='x', source_text='sample', version='v1')
        result = self.run_check()
        self.assertEqual(result['database'], 'ready')
        self.assertEqual(result['queue'], {'pending': 1})
        self.assertEqual(QuestionExtraction.objects.count(), 1)
        self.assertEqual(QuestionExtraction.objects.get().status, 'pending')

    def test_missing_migrations_stop_before_provider_requests(self):
        with patch('apps.bot.management.commands.check_ai.MigrationRecorder.applied_migrations', return_value={}), \
             patch('apps.bot.management.commands.check_ai._extract_from_chunk') as provider:
            result = self.run_check(fails=True, probe=True)
        provider.assert_not_called()
        self.assertEqual(result['database'], 'migrations_required')
        self.assertEqual(len(result['missing_migrations']), 2)

    def test_active_cooldown_prevents_probe_and_is_not_modified(self):
        due = timezone.now() + timedelta(minutes=15)
        job = QuestionExtraction.objects.create(source_hash='x', source_text='sample', version='v1',
            next_attempt_at=due, error_message='Gemini quota reached; waiting')
        with patch('apps.bot.management.commands.check_ai._extract_from_chunk') as provider:
            result = self.run_check(fails=True, probe=True)
        provider.assert_not_called()
        self.assertIn('cooldown_until', result)
        job.refresh_from_db()
        self.assertEqual(job.next_attempt_at, due)

    def test_database_errors_never_print_connection_details(self):
        with patch('apps.bot.management.commands.check_ai.MigrationRecorder.applied_migrations', side_effect=RuntimeError('private-database-password')):
            result = self.run_check(fails=True)
        self.assertEqual(result['database'], 'unavailable')
        self.assertNotIn('private-database-password', json.dumps(result))
