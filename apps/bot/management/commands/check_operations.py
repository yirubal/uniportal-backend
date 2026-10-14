"""Read-only operational checks for a scheduler/alert runner, separate from HTTP."""
import json
import shutil
from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Min, Q
from django.utils import timezone

from apps.bot.worker import work_types


class Command(BaseCommand):
    help = 'Report queue, stale claims, disk and optional backup freshness; exit nonzero on problems.'

    def add_arguments(self, parser):
        parser.add_argument('--backlog-seconds', type=int, default=900)
        parser.add_argument('--max-pending', type=int, default=1000)
        parser.add_argument('--max-failed', type=int, default=0)
        parser.add_argument('--disk-percent', type=int, default=85)
        parser.add_argument('--backup-status-file', type=Path)
        parser.add_argument('--backup-hours', type=int, default=26)

    def handle(self, *args, **options):
        if (options['backlog_seconds'] < 1 or options['max_pending'] < 0
                or options['max_failed'] < 0 or not 1 <= options['disk_percent'] <= 100
                or options['backup_hours'] < 1):
            raise CommandError('Thresholds must be positive; count thresholds may be zero.')
        now = timezone.now()
        stale_cutoff = now - timedelta(seconds=settings.WORKER_CLAIM_TIMEOUT_SECONDS)
        unhealthy = False
        queues = {}
        for kind, (model, status_field, _, pending) in work_types().items():
            pending_q = Q(**{status_field: pending})
            processing_q = Q(**{status_field: 'processing'})
            summary = model.objects.aggregate(
                pending=Count('pk', filter=pending_q),
                processing=Count('pk', filter=processing_q),
                failed=Count('pk', filter=Q(**{status_field: 'failed'})),
                stale=Count('pk', filter=processing_q & (Q(claimed_at__lt=stale_cutoff) | Q(claimed_at__isnull=True))),
                earliest_due=Min('next_attempt_at', filter=pending_q),
            )
            due = summary.pop('earliest_due')
            summary['overdue_seconds'] = max(0, int((now - due).total_seconds())) if due else 0
            summary['healthy'] = (not summary['stale'] and summary['failed'] <= options['max_failed']
                and summary['pending'] <= options['max_pending']
                and summary['overdue_seconds'] < options['backlog_seconds'])
            unhealthy |= not summary['healthy']
            queues[kind] = summary

        # The worker writes temporary files here; container/volume usage is distinct.
        import tempfile
        disk = {}
        for name, path in (('temporary', Path(tempfile.gettempdir())), ('media', Path(settings.MEDIA_ROOT))):
            while not path.exists():
                path = path.parent
            usage = shutil.disk_usage(path)
            percent = round(100 * usage.used / usage.total, 1)
            disk[name] = {'used_percent': percent, 'healthy': percent < options['disk_percent']}
            unhealthy |= not disk[name]['healthy']

        backup = {'status': 'unverified'}
        if options['backup_status_file']:
            try:
                data = json.loads(options['backup_status_file'].read_text())
                # An actual backup task writes BOTH timestamps only after successful archival.
                ages = {}
                for name in ('database', 'media'):
                    timestamp = datetime.fromisoformat(data[f'{name}_completed_at'])
                    if timestamp.tzinfo is None:
                        raise ValueError('Backup timestamp needs a timezone')
                    age = (now - timestamp.astimezone(datetime_timezone.utc)).total_seconds()
                    if age < -60:
                        raise ValueError('Future backup timestamp')
                    ages[name] = round(max(0, age) / 3600, 2)
                fresh = all(age <= options['backup_hours'] for age in ages.values())
                backup = {'status': 'fresh' if fresh else 'overdue', 'age_hours': ages}
                unhealthy |= not fresh
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                backup = {'status': 'invalid_or_missing'}
                unhealthy = True
        report = {'healthy': not unhealthy, 'queues': queues, 'disk': disk, 'backup': backup}
        self.stdout.write(json.dumps(report, sort_keys=True))
        if unhealthy:
            raise CommandError('Operational thresholds exceeded; see the JSON report.')
