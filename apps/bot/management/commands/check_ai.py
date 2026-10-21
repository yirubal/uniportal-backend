"""Read-only AI readiness and an explicit, synthetic two-request provider probe."""
import json
from types import SimpleNamespace
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count
from django.utils import timezone

from apps.bot.extractor import GeminiQuotaExceeded, _extract_from_chunk
from apps.bot.generation import _generate_batch
from apps.bot.models import QuestionExtraction

REQUIRED_MIGRATIONS = [('bot', '0004_practice_paper_generation'), ('quiz', '0015_practice_paper_generation')]
EXTRACTION_SAMPLE = '''Synthetic verification exam. Question 1: How long may a borrower keep a book?
A. Fourteen days
B. Two days
C. Thirty days
D. One day
Correct answer: A. Explanation: The fictional library permits loans for fourteen days.'''
GENERATION_SAMPLE = '''A fictional library opens at 08:00 and closes at 18:00 each day.
Registered borrowers may borrow up to three books at a time. Each loan lasts fourteen days.
Borrowers must return books to the front desk. Only registered borrowers may borrow books.'''


class Command(BaseCommand):
    help = ('Check AI configuration without requests or writes. --database checks migrations/queue; '
            '--probe makes at most two Gemini requests using synthetic text and saves nothing.')
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--database', action='store_true', help='Read migration and AI queue readiness from the configured database.')
        parser.add_argument('--probe', action='store_true', help='Use provider quota for one synthetic extraction and one generated MCQ; no automatic retries.')

    def handle(self, *args, **options):
        report = {'healthy': bool(settings.GEMINI_API_KEY), 'model': settings.GEMINI_MODEL,
            'key_configured': bool(settings.GEMINI_API_KEY), 'database': 'not_checked',
            'provider': 'not_tested', 'provider_requests_attempted': 0}
        if options['database']:
            try:
                applied = MigrationRecorder(connection).applied_migrations()
                missing = ['.'.join(item) for item in REQUIRED_MIGRATIONS if item not in applied]
                report['missing_migrations'] = missing
                report['database'] = 'migrations_required' if missing else 'ready'
                if missing:
                    report['healthy'] = False
                else:
                    report['queue'] = dict(QuestionExtraction.objects.order_by().values('status')
                        .annotate(total=Count('pk')).values_list('status', 'total'))
                    cooldown = (QuestionExtraction.objects.filter(next_attempt_at__gt=timezone.now(),
                        error_message__startswith='Gemini quota reached;').order_by('-next_attempt_at')
                        .values_list('next_attempt_at', flat=True).first())
                    if cooldown:
                        report['cooldown_until'] = cooldown.isoformat()
                        report['healthy'] = False
            except Exception:
                # Connection errors can include credentials/DSNs. Never print them.
                report.update(healthy=False, database='unavailable')
        if options['probe'] and report['healthy']:
            report['provider'] = 'extraction'
            try:
                report['provider_requests_attempted'] += 1
                extracted = _extract_from_chunk(settings.GEMINI_API_KEY, EXTRACTION_SAMPLE)
                if (len(extracted) != 1 or extracted[0]['correct_option'] != 'a'
                        or extracted[0]['option_a'].casefold() != 'fourteen days'):
                    raise ValueError('Synthetic extraction did not preserve its supplied answer.')
                report['extraction'] = 'passed'
                report['provider'] = 'generation'
                job = SimpleNamespace(source_text=GENERATION_SAMPLE, submission_token=uuid4(),
                    generation_settings={'count': 1, 'question_type': 'mcq', 'difficulty': 'easy', 'focus': 'Library borrowing rules'})
                report['provider_requests_attempted'] += 1
                _generate_batch(job, 1, [])
                report.update(generation='passed', provider='passed')
            except GeminiQuotaExceeded:
                report.update(healthy=False, provider='quota_reached')
            except ValueError:
                report.update(healthy=False, provider='request_or_validation_failed')
            except Exception:
                report.update(healthy=False, provider='provider_unavailable')
        self.stdout.write(json.dumps(report, sort_keys=True))
        if not report['healthy']:
            raise CommandError('AI verification did not pass; see the sanitized JSON report.')
