"""Explicit PostgreSQL work claiming and bounded subprocess execution."""
import logging
import os
import signal
import subprocess
import sys
from datetime import timedelta
from tempfile import TemporaryDirectory
from uuid import uuid4

from telegram.error import BadRequest, Forbidden, RetryAfter

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


class RetryLater(Exception):
    def __init__(self, delay):
        self.delay = max(1, int(delay))
        super().__init__('Telegram rate limit; retry scheduled.')


def work_types():
    from apps.content.models import FileInbox
    from apps.exams.models import ExamPDFUpload
    from .models import NotificationDelivery, QuestionExtraction, TelegramUpdate
    # Existing inbox/upload records remain their own work queue.
    return {
        'update': (TelegramUpdate, 'status', 'error_message', 'pending'),
        'notification': (NotificationDelivery, 'status', 'error_message', 'pending'),
        'inbox': (FileInbox, 'processing_status', 'processing_error', 'unprocessed'),
        'exam': (ExamPDFUpload, 'status', 'error_message', 'pending'),
        'ai': (QuestionExtraction, 'status', 'error_message', 'pending'),
    }


def claim_work(kind):
    model, status_field, error_field, pending = work_types()[kind]
    now = timezone.now()
    candidates = model.objects.filter(**{
        status_field: pending, 'next_attempt_at__lte': now,
        'attempt_count__lt': settings.WORKER_MAX_ATTEMPTS,
    }).order_by('next_attempt_at', 'pk').values_list('pk', flat=True)[:20]
    for pk in candidates:
        token = uuid4()
        claimed = model.objects.filter(pk=pk, next_attempt_at__lte=now, attempt_count__lt=settings.WORKER_MAX_ATTEMPTS, **{status_field: pending}).update(**{
            status_field: 'processing', 'claimed_at': now, 'claim_token': token,
            'attempt_count': F('attempt_count') + 1,
        })
        if claimed:
            logger.info('job_kind=%s job_id=%s claim_id=%s state=claimed', kind, pk, token)
            return pk, token
    return None


def refresh_broadcast(broadcast_id):
    if not broadcast_id:
        return
    from apps.accounts.models import BroadcastMessage
    from .models import NotificationDelivery
    # Lock the parent so concurrent delivery completions cannot overwrite totals.
    with transaction.atomic():
        broadcast = BroadcastMessage.objects.select_for_update().get(pk=broadcast_id)
        deliveries = NotificationDelivery.objects.filter(broadcast_id=broadcast_id)
        broadcast.success_count = deliveries.filter(status='processed').count()
        broadcast.failed_count = deliveries.filter(status='failed').count()
        broadcast.save(update_fields=['success_count', 'failed_count'])


def refresh_exam_reminder(log_id):
    if not log_id:
        return
    from apps.exams.models import ExamNotificationLog
    from .models import NotificationDelivery
    with transaction.atomic():
        log = ExamNotificationLog.objects.select_for_update().get(pk=log_id)
        deliveries = NotificationDelivery.objects.filter(exam_notification_id=log_id)
        log.sent_count = deliveries.filter(status='processed').count()
        log.failed_count = deliveries.filter(status='failed').count()
        log.save(update_fields=['sent_count', 'failed_count'])


def fail_work(kind, pk, token, error, *, permanent=False, delay=None):
    model, status_field, error_field, pending = work_types()[kind]
    with transaction.atomic():
        row = model.objects.select_for_update().filter(pk=pk, claim_token=token, **{status_field: 'processing'}).first()
        if row is None:
            return
        terminal = permanent or row.attempt_count >= settings.WORKER_MAX_ATTEMPTS
        next_time = timezone.now() + timedelta(seconds=delay or min(3600, 30 * 2 ** (row.attempt_count - 1)))
        model.objects.filter(pk=pk, claim_token=token).update(**{
            status_field: 'failed' if terminal else pending, error_field: str(error)[:2000],
            'claimed_at': None, 'claim_token': None, 'next_attempt_at': next_time,
        })
        if kind == 'notification':
            refresh_broadcast(row.broadcast_id)
            refresh_exam_reminder(row.exam_notification_id)
    logger.warning('job_kind=%s job_id=%s claim_id=%s state=%s attempt=%s',
                   kind, pk, token, 'failed' if terminal else 'retry', row.attempt_count)


def recover_stale_claims(kind=None):
    count = 0
    cutoff = timezone.now() - timedelta(seconds=settings.WORKER_CLAIM_TIMEOUT_SECONDS)
    for name, (model, status_field, _, _) in work_types().items():
        if kind and name != kind:
            continue
        # Null claim time is a legacy interrupted job, not an active new claim.
        from django.db.models import Q
        stale = model.objects.filter(**{status_field: 'processing'}).filter(
            Q(claimed_at__lt=cutoff) | Q(claimed_at__isnull=True),
        ).values_list('pk', 'claim_token')[:100]
        for pk, token in stale:
            fail_work(name, pk, token, 'Interrupted worker claim; retry scheduled.')
            count += 1
    return count


def run_claimed_subprocess(kind, pk, token):
    """Kill the full process group on timeout, including OCR descendants."""
    with TemporaryDirectory(prefix='uniportal-work-') as temporary_directory:
        process = subprocess.Popen(
            [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'run_work_item', kind, str(pk), str(token)],
            start_new_session=True, env={**os.environ, 'TMPDIR': temporary_directory},
        )
        try:
            process.wait(timeout=settings.WORKER_TASK_TIMEOUT_SECONDS)
            if process.returncode:
                fail_work(kind, pk, token, 'Worker subprocess exited before completion.')
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            fail_work(kind, pk, token, 'Work exceeded the subprocess time limit.')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def process_claimed_work(kind, pk, token):
    from asgiref.sync import async_to_sync
    model, status_field, error_field, _ = work_types()[kind]
    row = model.objects.filter(pk=pk, claim_token=token, **{status_field: 'processing'}).first()
    if row is None:
        return
    try:
        changes = {}
        if kind == 'update':
            from .application import process_telegram_update
            async_to_sync(process_telegram_update)(row.payload)
        elif kind == 'notification':
            deliver_notification(row)
        elif kind == 'inbox':
            from .tasks import process_inbox_item
            changes = process_inbox_item(row)
        elif kind == 'exam':
            from apps.exams.services import process_attendance_pdf, process_schedule_pdf
            # Parsing/import and successful status commit together. A killed
            # child or failed import cannot leave half an upload's rows behind.
            with transaction.atomic():
                model.objects.select_for_update().get(pk=pk, claim_token=token)
                processor = process_schedule_pdf if row.pdf_type == 'schedule' else process_attendance_pdf
                success, _, error = processor(row)
                if not success:
                    raise ValueError(error)
        elif kind == 'ai':
            from .ai_tasks import process_question_extraction
            process_question_extraction(row)
        model.objects.filter(pk=pk, claim_token=token).update(**{
            status_field: 'processed', error_field: changes.pop(error_field, ''),
            'claimed_at': None, 'claim_token': None, **changes,
        })
        if kind == 'notification':
            refresh_broadcast(row.broadcast_id)
            refresh_exam_reminder(row.exam_notification_id)
        logger.info('job_kind=%s job_id=%s claim_id=%s state=processed', kind, pk, token)
    except RetryLater as exc:
        if kind == 'notification':
            from .models import NotificationDelivery
            available = timezone.now() + timedelta(seconds=exc.delay)
            NotificationDelivery.objects.filter(status='pending', next_attempt_at__lt=available).update(next_attempt_at=available)
        fail_work(kind, pk, token, exc, delay=exc.delay)
    except RetryAfter as exc:
        delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, timedelta) else exc.retry_after
        fail_work(kind, pk, token, 'Telegram rate limit; retry scheduled.', delay=delay)
    except (ValueError, BadRequest, Forbidden) as exc:
        fail_work(kind, pk, token, exc, permanent=True)
    except Exception as exc:
        # Avoid persisting HTTP URLs that may contain bot/API credentials.
        fail_work(kind, pk, token, f'{type(exc).__name__}: processing failed; inspect worker logs.')
        logger.error('job_kind=%s job_id=%s claim_id=%s error_type=%s', kind, pk, token, type(exc).__name__)


def deliver_notification(delivery):
    import httpx
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError('Telegram bot is not configured')
    payload = {'chat_id': delivery.chat_id, 'text': delivery.text}
    if delivery.parse_mode:
        payload['parse_mode'] = delivery.parse_mode
    response = httpx.post(
        f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage', json=payload, timeout=10,
    )
    if response.status_code >= 500:
        raise RuntimeError('Telegram unavailable')
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError('Invalid Telegram response') from exc
    if response.status_code == 429 or data.get('error_code') == 429:
        raise RetryLater(data.get('parameters', {}).get('retry_after', 30))
    if not data.get('ok'):
        raise ValueError('Telegram refused delivery; check recipient and message formatting.')
