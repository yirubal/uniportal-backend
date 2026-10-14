"""Bounded, read-only orphan audit. Never delete bucket objects automatically."""
import os
from datetime import timedelta
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from storages.backends.s3 import S3Storage

from apps.content.services import file_is_referenced


class Command(BaseCommand):
    help = 'Report old unreferenced objects under one managed prefix; never deletes files.'

    def add_arguments(self, parser):
        parser.add_argument('--prefix', choices=['inbox', 'resources', 'exam_pdfs'], required=True)
        parser.add_argument('--limit', type=int, default=500)
        parser.add_argument('--min-age-days', type=int, default=30)
        parser.add_argument('--after', default='', help='S3 key from the previous page (lexical cursor).')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 1000 or options['min_age_days'] < 7:
            raise CommandError('Limit must be 1–1000 and minimum age at least seven days.')
        prefix = options['prefix'] + '/'
        cutoff = timezone.now() - timedelta(days=options['min_age_days'])
        storage = default_storage
        if isinstance(storage, S3Storage):
            root = storage.location.strip('/')
            full_prefix = (root + '/' if root else '') + prefix
            params = {'Bucket': storage.bucket_name, 'Prefix': full_prefix, 'MaxKeys': options['limit']}
            if options['after']:
                if not options['after'].startswith(full_prefix):
                    raise CommandError('Cursor must be within the selected prefix.')
                params['StartAfter'] = options['after']
            page = storage.connection.meta.client.list_objects_v2(**params)
            objects = [(row['Key'][len(root) + 1:] if root else row['Key'], row['LastModified'])
                       for row in page.get('Contents', []) if not row['Key'].endswith('/')]
            if page.get('IsTruncated') and page.get('Contents'):
                self.stdout.write('Next --after: ' + page['Contents'][-1]['Key'])
        else:
            root = Path(storage.location).resolve()
            objects = []
            for directory, _, names in os.walk(root / options['prefix'], followlinks=False):
                for name in names:
                    path = Path(directory) / name
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        continue
                    objects.append((str(path.relative_to(root)), timezone.datetime.fromtimestamp(path.stat().st_mtime, timezone.get_current_timezone())))
                    if len(objects) >= options['limit']:
                        break
                if len(objects) >= options['limit']:
                    break
        candidates = 0
        for name, modified in objects:
            if modified < cutoff and not file_is_referenced(name):
                candidates += 1
                self.stdout.write('Review orphan candidate: ' + name)
        self.stdout.write(f'Inspected {len(objects)} object(s); {candidates} candidate(s). No files deleted. Confirm backups and references before any manual deletion.')
