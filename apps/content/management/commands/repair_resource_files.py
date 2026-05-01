from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from apps.content.models import Resource
from apps.content.services import clear_inbox_file, copy_inbox_file_to_resource


class Command(BaseCommand):
    help = 'Copies existing FileInbox files into their assigned Resource files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be repaired without writing files.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        repaired = 0
        already_ok = 0
        missing_source = 0
        failed = 0
        cleaned = 0

        resources = Resource.objects.select_related('inbox_source').filter(
            inbox_source__isnull=False,
        )

        for resource in resources:
            if self._file_exists(resource.file):
                if self._file_exists(resource.inbox_source.file):
                    if dry_run:
                        cleaned += 1
                        self.stdout.write(
                            f'Would delete duplicate inbox file for resource {resource.id}: '
                            f'{resource.inbox_source.file.name}'
                        )
                    elif clear_inbox_file(
                        resource.inbox_source,
                        protected_file_name=resource.file.name,
                    ):
                        cleaned += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Deleted duplicate inbox file for resource {resource.id}'
                            )
                        )
                already_ok += 1
                continue

            inbox_item = resource.inbox_source
            if not inbox_item.file:
                missing_source += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'Missing inbox source for resource {resource.id}: {resource.title}'
                    )
                )
                continue

            if dry_run:
                can_repair = (
                    self._file_exists(inbox_item.file) or
                    self._local_media_file_exists(inbox_item.file.name)
                )
                if can_repair:
                    repaired += 1
                    self.stdout.write(
                        f'Would repair resource {resource.id} from {inbox_item.file.name}'
                    )
                else:
                    missing_source += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'Cannot repair resource {resource.id}; source file missing: '
                            f'{inbox_item.file.name}'
                        )
                    )
                continue

            try:
                if self._file_exists(inbox_item.file):
                    copy_inbox_file_to_resource(inbox_item, resource)
                    resource.save(update_fields=['file', 'updated_at'])
                else:
                    local_path = Path(settings.MEDIA_ROOT) / inbox_item.file.name
                    if not local_path.exists():
                        missing_source += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f'Cannot repair resource {resource.id}; source file missing: '
                                f'{inbox_item.file.name}'
                            )
                        )
                        continue

                    with open(local_path, 'rb') as handle:
                        resource.file.save(
                            Path(inbox_item.original_filename or inbox_item.file.name).name,
                            File(handle),
                            save=False,
                        )
                    resource.save(update_fields=['file', 'updated_at'])

                repaired += 1
                if clear_inbox_file(
                    inbox_item,
                    protected_file_name=resource.file.name,
                ):
                    cleaned += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Repaired resource {resource.id}: {resource.file.name}'
                    )
                )
            except Exception as exc:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'Failed resource {resource.id}: {exc}'
                    )
                )

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                'Done. '
                f'repaired={repaired}, already_ok={already_ok}, '
                f'cleaned={cleaned}, missing_source={missing_source}, failed={failed}'
            )
        )

    def _file_exists(self, field_file):
        if not field_file or not field_file.name:
            return False
        try:
            return field_file.storage.exists(field_file.name)
        except Exception:
            return False

    def _local_media_file_exists(self, name):
        if not name:
            return False
        return (Path(settings.MEDIA_ROOT) / name).exists()
