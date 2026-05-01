from django.core.management.base import BaseCommand

from apps.content.services import cleanup_assigned_inbox_duplicates


class Command(BaseCommand):
    help = 'Deletes duplicate inbox files after their assigned Resource file exists.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report duplicate inbox files without deleting them.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum assigned inbox rows to inspect.',
        )

    def handle(self, *args, **options):
        stats, messages = cleanup_assigned_inbox_duplicates(
            dry_run=options['dry_run'],
            limit=options['limit'],
        )

        for message in messages:
            self.stdout.write(message)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Done. '
            f'checked={stats["checked"]}, cleaned={stats["cleaned"]}, '
            f'skipped_missing_resource_file={stats["skipped_missing_resource_file"]}, '
            f'skipped_missing_inbox_file={stats["skipped_missing_inbox_file"]}, '
            f'skipped_same_file={stats["skipped_same_file"]}, '
            f'failed={stats["failed"]}'
        ))
