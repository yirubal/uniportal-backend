from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from psycopg2.extensions import make_dsn

from apps.bot.backups import create_backup, prune_backups


class Command(BaseCommand):
    help = 'Back up PostgreSQL and private R2 before maintenance; retain 30 days.'

    def handle(self, *args, **options):
        db = connections['default']
        if db.vendor != 'postgresql' or not hasattr(default_storage, 'bucket_name'):
            raise CommandError('Production backup requires PostgreSQL and private S3/R2 storage.')
        try:
            db.ensure_connection()
            # psycopg2's printable DSN masks passwords. Fetch it only in memory;
            # pg_dump receives it through its environment, never command arguments.
            parameters = db.connection.get_dsn_parameters()
            parameters['password'] = db.connection.info.password or ''
            dsn = make_dsn(**parameters)
            _, manifest = create_backup(dsn, default_storage.connection.meta.client,
                default_storage.bucket_name, progress=self.stdout.write)
            removed = prune_backups(default_storage.connection.meta.client, default_storage.bucket_name)
        except Exception as exc:
            raise CommandError(f'Backup failed ({type(exc).__name__}); maintenance must not run.') from None
        self.stdout.write(f'Backup complete: {len(manifest["media"])} media objects; {removed} expired backup objects removed.')
