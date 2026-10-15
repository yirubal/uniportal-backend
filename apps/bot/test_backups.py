import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from unittest import skipUnless
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from botocore.exceptions import ReadTimeoutError
from psycopg2.extensions import make_dsn

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from apps.bot.backups import PREFIX, backup_media, create_backup, database_fingerprint, object_hash, pg_environment, prune_backups


class MemoryS3:
    """Byte storage fixture: no network, credentials or production object keys."""
    def __init__(self):
        self.objects = {}
        self.copies = 0

    def put_object(self, *, Bucket, Key, Body, Metadata=None, **kwargs):
        self.objects[Key] = {'Body': Body, 'Metadata': Metadata or {},
            'LastModified': datetime.now(timezone.utc), 'ETag': '"' + hashlib.md5(Body).hexdigest() + '"'}

    def get_object(self, *, Bucket, Key, IfMatch=None):
        obj = self.objects[Key]
        if IfMatch and IfMatch != obj['ETag']:
            raise ValueError('Source changed')
        return {'Body': BytesIO(obj['Body'])}

    def head_object(self, *, Bucket, Key):
        obj = self.objects[Key]
        return {'ContentLength': len(obj['Body']), 'Metadata': obj['Metadata']}

    def copy_object(self, *, Bucket, Key, CopySource, CopySourceIfMatch, Metadata, **kwargs):
        obj = self.objects[CopySource['Key']]
        if obj['ETag'] != CopySourceIfMatch:
            raise ValueError('Source changed')
        self.copies += 1
        self.put_object(Bucket=Bucket, Key=Key, Body=obj['Body'], Metadata=Metadata)

    def upload_file(self, filename, bucket, key):
        with open(filename, 'rb') as handle:
            self.put_object(Bucket=bucket, Key=key, Body=handle.read())

    def delete_object(self, *, Bucket, Key):
        del self.objects[Key]

    def get_paginator(self, operation):
        return self

    def paginate(self, *, Bucket, Prefix=''):
        return [{'Contents': [{'Key': key, 'Size': len(obj['Body']),
            'ETag': obj['ETag'], 'LastModified': obj['LastModified']}
            for key, obj in self.objects.items() if key.startswith(Prefix)]}]


class BackupSafetyTests(SimpleTestCase):
    def setUp(self):
        self.client = MemoryS3()
        self.client.put_object(Bucket='private', Key='resources/test.pdf', Body=b'synthetic PDF bytes')

    def source(self):
        return self.client.paginate(Bucket='private')[0]['Contents'][0]

    def test_media_is_verified_reused_and_old_version_survives_replacement(self):
        first = backup_media(self.client, 'private', self.source(), set())
        self.assertEqual(first['sha256'], object_hash(self.client, 'private', first['backup_key']))
        again = backup_media(self.client, 'private', self.source(), {first['backup_key']})
        self.assertEqual(first, again)
        self.assertEqual(self.client.copies, 1)
        self.client.put_object(Bucket='private', Key='resources/test.pdf', Body=b'replacement')
        second = backup_media(self.client, 'private', self.source(), {first['backup_key']})
        self.assertNotEqual(first['backup_key'], second['backup_key'])
        self.assertEqual(object_hash(self.client, 'private', first['backup_key']), first['sha256'])

    def test_changed_source_is_not_silently_copied(self):
        source = self.source()
        self.client.put_object(Bucket='private', Key=source['Key'], Body=b'changed')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            backup_media(self.client, 'private', source, set())
        self.assertEqual(self.client.copies, 0)

    def test_corrupt_copy_or_existing_metadata_fails(self):
        with patch('apps.bot.backups.object_hash', side_effect=['a' * 64, 'b' * 64]):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                backup_media(self.client, 'private', self.source(), set())
        self.assertFalse(any(key.startswith(PREFIX) for key in self.client.objects))
        entry = backup_media(self.client, 'private', self.source(), set())
        key = entry['backup_key']
        self.client.objects[key]['Metadata'] = {}
        with self.assertRaisesRegex(ValueError, 'integrity'):
            backup_media(self.client, 'private', self.source(), {key})

    @patch('apps.bot.backups.time.sleep')
    def test_stream_timeout_retries_are_bounded(self, sleep):
        timeout = ReadTimeoutError(endpoint_url='https://example.invalid')
        with patch('apps.bot.backups._backup_media_once', side_effect=[timeout, {'verified': True}]):
            self.assertEqual(backup_media(self.client, 'private', self.source(), set()), {'verified': True})
        sleep.reset_mock()
        with patch('apps.bot.backups._backup_media_once', side_effect=timeout) as attempt:
            with self.assertRaises(ReadTimeoutError):
                backup_media(self.client, 'private', self.source(), set())
        self.assertEqual(attempt.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_pg_credentials_stay_in_environment_and_correct_database_is_selected(self):
        with patch.dict(os.environ, {'PGDATABASE': 'wrong', 'PGSERVICE': 'wrong'}):
            env = pg_environment('dbname=backup_source user=backup_user password=private-password host=localhost')
        self.assertEqual(env['PGDATABASE'], 'backup_source')
        self.assertEqual(env['PGPASSWORD'], 'private-password')
        self.assertNotIn('PGDBNAME', env)
        self.assertNotIn('PGSERVICE', env)

    def test_backup_command_uses_real_password_in_memory_and_hides_failure_details(self):
        module = 'apps.bot.management.commands.backup_production.'
        db = Mock(vendor='postgresql')
        db.connection.get_dsn_parameters.return_value = {'dbname': 'example', 'user': 'example'}
        db.connection.info.password = 'synthetic-private-password'
        storage = SimpleNamespace(bucket_name='private', connection=SimpleNamespace(meta=SimpleNamespace(client=MemoryS3())))
        with patch(module + 'connections', {'default': db}), patch(module + 'default_storage', storage), \
                patch(module + 'create_backup', side_effect=ValueError('synthetic-private-password')) as backup:
            with self.assertRaises(CommandError) as result:
                call_command('backup_production', stdout=StringIO())
        self.assertEqual(pg_environment(backup.call_args.args[0])['PGPASSWORD'], 'synthetic-private-password')
        self.assertNotIn('synthetic-private-password', str(result.exception))

    def test_retention_preserves_recent_snapshots_shared_media_and_unrelated_objects(self):
        old = datetime.now(timezone.utc) - timedelta(days=31)
        stale = PREFIX + 'snapshots/20200101T000000Z-' + 'a' * 32 + '/'
        current = PREFIX + 'snapshots/20990101T000000Z-' + 'b' * 32 + '/'
        shared, unused = PREFIX + 'media/shared', PREFIX + 'media/unused'
        for key in (stale + 'database.dump', shared, unused, 'operations/backups/exam-duplicate-cleanup/saved.json'):
            self.client.put_object(Bucket='private', Key=key, Body=b'keep or expire')
            self.client.objects[key]['LastModified'] = old
        for key in (stale + 'manifest.json', current + 'manifest.json'):
            self.client.put_object(Bucket='private', Key=key, Body=json.dumps({'media': [{'backup_key': shared}]}).encode())
        self.client.objects[stale + 'manifest.json']['LastModified'] = old
        self.assertEqual(prune_backups(self.client, 'private'), 3)
        self.assertIn(shared, self.client.objects)
        self.assertIn('resources/test.pdf', self.client.objects)
        self.assertIn('operations/backups/exam-duplicate-cleanup/saved.json', self.client.objects)
        self.assertIn(current + 'manifest.json', self.client.objects)

    def test_retention_refuses_without_a_recent_completed_backup(self):
        with self.assertRaisesRegex(ValueError, 'No recent completed backup'):
            prune_backups(self.client, 'private')

    @patch('apps.bot.management.commands.run_maintenance.call_command')
    def test_backup_failure_stops_all_maintenance_changes(self, command):
        command.side_effect = CommandError('Backup failed')
        with self.assertRaises(CommandError):
            call_command('run_maintenance', backup=True, stdout=StringIO())
        command.assert_called_once_with('backup_production', stdout=command.call_args.kwargs['stdout'])

    @patch('apps.bot.management.commands.run_maintenance.ThrottleCacheEntry')
    @patch('apps.bot.management.commands.run_maintenance.call_command')
    def test_backup_runs_before_existing_maintenance(self, command, throttle):
        throttle.objects.filter.return_value.delete.return_value = (2, {})
        call_command('run_maintenance', backup=True, stdout=StringIO())
        self.assertEqual([call.args[0] for call in command.call_args_list],
            ['backup_production', 'check_subscriptions', 'send_exam_notifications',
             'cleanup_duplicate_inbox_files', 'compact_completed_work'])


@skipUnless(connection.vendor == 'postgresql' and shutil.which('pg_dump'), 'Requires PostgreSQL and pg_dump')
class RealDatabaseBackupTests(TransactionTestCase):
    def test_row_hash_order_is_bytewise_even_when_database_locale_differs(self):
        from apps.accounts.models import Student
        Student.objects.bulk_create([Student(id=pk, telegram_id=987650000 + pk,
            first_name='Synthetic locale test') for pk in range(1, 13)])
        actual = database_fingerprint(connection)['accounts_student']
        with connection.cursor() as cursor:
            cursor.execute('SELECT row_to_json(t)::text FROM accounts_student t')
            rows = sorted(row[0].encode() for row in cursor.fetchall())
        expected = hashlib.sha256(b''.join(row + b'\n' for row in rows)).hexdigest()
        self.assertEqual(actual, {'rows': 12, 'sha256': expected})

    def test_actual_pg_dump_has_complete_snapshot_and_private_completion_marker(self):
        from apps.accounts.models import Student
        from apps.content.models import Resource
        Student.objects.create(telegram_id=987654321, first_name='Synthetic backup test')
        Resource.objects.create(title='Synthetic backup', file='resources/synthetic.pdf')
        client = MemoryS3()
        client.put_object(Bucket='private', Key='resources/synthetic.pdf', Body=b'synthetic bytes')
        params = connection.connection.get_dsn_parameters()
        params['password'] = connection.connection.info.password or ''
        key, manifest = create_backup(make_dsn(**params), client, 'private')
        self.assertTrue(key.endswith('/manifest.json'))
        self.assertEqual(manifest['tables']['accounts_student']['rows'], 1)
        self.assertEqual(len(manifest['media']), 1)
        self.assertEqual(client.objects[key]['Body'], json.dumps(manifest, sort_keys=True).encode())
        self.assertEqual(manifest['database']['sha256'], object_hash(client, 'private', manifest['database']['backup_key']))

    def test_missing_referenced_media_does_not_publish_completion(self):
        from apps.content.models import Resource
        Resource.objects.create(title='Missing media', file='resources/missing.pdf')
        client = MemoryS3()
        params = connection.connection.get_dsn_parameters()
        params['password'] = connection.connection.info.password or ''
        with self.assertRaisesRegex(ValueError, 'missing media'):
            create_backup(make_dsn(**params), client, 'private')
        self.assertFalse(any(key.endswith('/manifest.json') for key in client.objects))
