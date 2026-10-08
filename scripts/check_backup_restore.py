"""Synthetic backup/restore drill on a disposable local PostgreSQL server.

DATABASE_URL must identify a local PostgreSQL connection with CREATEDB rights.
Creates and removes two uniquely named databases; never dumps the supplied DB.
"""

import hashlib
import os
from pathlib import Path
from contextlib import closing
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn


ROOT = Path(__file__).resolve().parent.parent


def database_fingerprint(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        tables = [row[0] for row in cursor.fetchall()]
        digest = hashlib.sha256()
        for table in tables:
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY 1').format(sql.Identifier(table)))
            digest.update(table.encode())
            for (row,) in cursor.fetchall():
                digest.update(row.encode())
                digest.update(b'\n')
        return digest.hexdigest()


def media_fingerprint(directory):
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob('*') if path.is_file()
    }


def main():
    supplied_url = os.environ.get('DATABASE_URL', '')
    parsed = urlsplit(supplied_url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise SystemExit('Use a disposable local PostgreSQL DATABASE_URL.')
    host = parse_dsn(supplied_url).get('host', '')
    if parsed.scheme not in ('postgres', 'postgresql') or not (
        host in ('localhost', '127.0.0.1', '::1') or host.startswith('/')
    ):
        raise SystemExit('Use a disposable local PostgreSQL DATABASE_URL; remote servers are refused.')

    source = 'uniportal_drill_' + uuid4().hex[:12]
    restored = source + '_restored'
    created = []
    admin = psycopg2.connect(supplied_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            for name in (source, restored):
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)

        # Preserve the triple slash used for Unix-socket PostgreSQL URLs.
        # A query-string dbname must not override our disposable database name.
        query_parameters = [(key, value) for key, value in parse_qsl(parsed.query) if key != 'dbname']
        query = '?' + urlencode(query_parameters) if query_parameters else ''
        source_url = f'{parsed.scheme}://{parsed.netloc}/{source}{query}'
        restored_url = f'{parsed.scheme}://{parsed.netloc}/{restored}{query}'
        with TemporaryDirectory(prefix='uniportal-backup-drill-') as work:
            work = Path(work)
            source_media = work / 'source-media'
            env = {
                **os.environ,
                'DJANGO_SETTINGS_MODULE': 'config.settings.test',
                'DATABASE_URL': source_url,
                'DRILL_MEDIA_ROOT': str(source_media),
            }
            subprocess.run(
                [sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=ROOT,
                env=env, check=True, stdout=subprocess.DEVNULL,
            )
            seed = '''
import os
from django.conf import settings
from django.core.files.base import ContentFile
from apps.accounts.models import Student
from apps.content.models import Course, Resource
settings.MEDIA_ROOT = os.environ['DRILL_MEDIA_ROOT']
Student.objects.create(telegram_id=987654321, first_name='Synthetic restore drill')
course = Course.objects.create(name='Restore drill course', code='DRILL')
resource = Resource.objects.create(title='Restore drill file', status='published', access_level='free')
resource.file.save('drill.pdf', ContentFile(b'%PDF-1.4 synthetic restore drill'))
resource.courses.add(course)
'''
            subprocess.run(
                [sys.executable, 'manage.py', 'shell', '--command', seed], cwd=ROOT,
                env=env, check=True, stdout=subprocess.DEVNULL,
            )
            with closing(psycopg2.connect(source_url)) as source_connection:
                expected = database_fingerprint(source_connection)

            parameters = admin.get_dsn_parameters()
            pg_env = {
                key: value for key, value in os.environ.items()
                if not key.startswith('PG')
            }
            for name in ('host', 'port', 'user', 'password', 'sslmode'):
                value = admin.info.password if name == 'password' else parameters.get(name)
                if value:
                    pg_env['PG' + name.upper()] = value
            archive = work / 'database.dump'
            subprocess.run(
                ['pg_dump', '--format=custom', '--file', str(archive), '--dbname', source],
                env=pg_env, check=True,
            )
            subprocess.run(
                ['pg_restore', '--exit-on-error', '--no-owner', '--no-privileges',
                 '--dbname', restored, str(archive)], env=pg_env, check=True,
            )
            with closing(psycopg2.connect(restored_url)) as restored_connection:
                if database_fingerprint(restored_connection) != expected:
                    raise RuntimeError('Restored database differs from the source.')

            shutil.copytree(source_media, work / 'media-backup')
            shutil.copytree(work / 'media-backup', work / 'restored-media')
            expected_media = media_fingerprint(source_media)
            if not expected_media or media_fingerprint(work / 'restored-media') != expected_media:
                raise RuntimeError('Restored media differs from the source.')
            print('Backup/restore drill passed: database rows, relationships, migrations, and media bytes match.')
    finally:
        with admin.cursor() as cursor:
            for name in reversed(created):
                cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__ == '__main__':
    main()
