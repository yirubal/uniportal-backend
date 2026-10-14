"""Fill Resource.file_size/page_count from stored files. Safe to re-run."""
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.content.models import Resource
from apps.content.services import storage_file_exists

PAGED_EXTENSIONS = {'pdf', 'docx', 'pptx'}


class Command(BaseCommand):
    help = 'Backfill missing file_size/page_count on resources by reading files from storage.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Recompute metadata for every resource.')

    def handle(self, *args, **options):
        queryset = Resource.objects.exclude(file='').order_by('pk')
        if not options['force']:
            queryset = queryset.filter(Q(file_size__isnull=True) | Q(page_count__isnull=True))

        checked = updated = skipped = missing = failed = 0
        for resource in queryset.iterator():
            checked += 1
            extension = Path(resource.file.name).suffix.lower().lstrip('.')
            if (
                not options['force']
                and resource.file_size is not None
                and extension not in PAGED_EXTENSIONS
            ):
                skipped += 1  # Page count does not apply to this type.
                continue
            if not storage_file_exists(resource.file):
                missing += 1
                self.stdout.write(self.style.WARNING(
                    f'Resource {resource.pk}: file missing in storage: {resource.file.name}'
                ))
                continue
            if not resource.refresh_file_metadata():
                failed += 1
                continue
            resource.save(update_fields=['file_size', 'page_count'])
            updated += 1

        self.stdout.write(
            f'Done. checked={checked}, updated={updated}, skipped_not_paged={skipped}, '
            f'missing_file={missing}, failed={failed}'
        )
