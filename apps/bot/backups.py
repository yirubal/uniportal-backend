"""Private PostgreSQL/R2 recovery snapshots, completed before daily maintenance."""
import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn
from botocore.exceptions import ConnectionClosedError, EndpointConnectionError, ReadTimeoutError

PREFIX = 'operations/backups/daily-v1/'


def object_hash(client, bucket, key, **kwargs):
    response = client.get_object(Bucket=bucket, Key=key, **kwargs)
    digest = hashlib.sha256()
    with response['Body'] as body:
        for chunk in iter(lambda: body.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def list_objects(client, bucket, prefix=''):
    return [item for page in client.get_paginator('list_objects_v2').paginate(
        Bucket=bucket, Prefix=prefix) for item in page.get('Contents', [])]


def database_fingerprint(connection):
    """Counts and deterministic row hashes from the same snapshot as pg_dump."""
    tables = {}
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        for (table,) in cursor.fetchall():
            digest = hashlib.sha256()
            # Source and recovery servers can have different default locales.
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text COLLATE "C" FROM {} t ORDER BY 1').format(sql.Identifier(table)))
            count = 0
            for (row,) in cursor:
                digest.update(row.encode() + b'\n')
                count += 1
            tables[table] = {'rows': count, 'sha256': digest.hexdigest()}
    return tables


def backup_media(client, bucket, source, existing):
    # Streaming-body reads can fail after the SDK's request-level retries finish.
    for attempt in range(3):
        try:
            return _backup_media_once(client, bucket, source, existing)
        except (ConnectionClosedError, EndpointConnectionError, ReadTimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def _backup_media_once(client, bucket, source, existing):
    key, etag = source['Key'], source['ETag']
    target = PREFIX + 'media/' + hashlib.sha256((key + '\0' + etag).encode()).hexdigest()
    if target in existing:
        head = client.head_object(Bucket=bucket, Key=target)
        digest = head.get('Metadata', {}).get('sha256', '')
        if head['ContentLength'] != source['Size'] or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Existing media backup failed integrity metadata checks')
    else:
        digest = object_hash(client, bucket, key, IfMatch=etag)
        client.copy_object(Bucket=bucket, Key=target,
            CopySource={'Bucket': bucket, 'Key': key}, CopySourceIfMatch=etag,
            MetadataDirective='REPLACE', Metadata={'sha256': digest})
        if object_hash(client, bucket, target) != digest:
            client.delete_object(Bucket=bucket, Key=target)
            raise ValueError('Media backup readback hash mismatch')
    return {'key': key, 'backup_key': target, 'bytes': source['Size'], 'sha256': digest}


def pg_environment(dsn):
    # Credentials stay out of process arguments, logs and persisted manifests.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    names = {'dbname': 'PGDATABASE', 'host': 'PGHOST', 'hostaddr': 'PGHOSTADDR',
        'port': 'PGPORT', 'user': 'PGUSER', 'password': 'PGPASSWORD',
        'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT',
        'sslcert': 'PGSSLCERT', 'sslkey': 'PGSSLKEY',
        'connect_timeout': 'PGCONNECT_TIMEOUT', 'options': 'PGOPTIONS'}
    for key, value in parse_dsn(dsn).items():
        if key in names:
            env[names[key]] = str(value)
    return env


def create_backup(dsn, client, bucket, progress=lambda message: None):
    now = datetime.now(timezone.utc)
    snapshot_key = PREFIX + 'snapshots/' + now.strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex
    manifest = {'version': 1, 'started_at': now.isoformat(), 'bucket': bucket,
        'table_hash_format': 'row-json-utf8-c-collation-utc-v1'}
    with psycopg2.connect(dsn, connect_timeout=15) as connection, TemporaryDirectory(prefix='uniportal-backup-') as directory:
        connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '120s'")
            cursor.execute('SELECT pg_export_snapshot()')
            snapshot = cursor.fetchone()[0]
            references = set()
            for table in ('content_resource', 'content_fileinbox', 'exams_exampdfupload'):
                cursor.execute(sql.SQL("SELECT file FROM {} WHERE file <> ''").format(sql.Identifier(table)))
                references.update(row[0] for row in cursor.fetchall())
        archive = Path(directory) / 'database.dump'
        result = subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-privileges',
            '--snapshot', snapshot, '--file', str(archive)], env=pg_environment(dsn),
            capture_output=True, timeout=300)
        if result.returncode:
            raise ValueError('pg_dump failed; check client/server compatibility and database access')
        progress('Database snapshot dumped; verifying table fingerprints.')
        manifest['tables'] = database_fingerprint(connection)
        # Finish the database snapshot before lengthy media I/O; no write locks held.
        connection.commit()
        media = [item for item in list_objects(client, bucket) if not item['Key'].startswith('operations/backups/')]
        if references - {item['Key'] for item in media}:
            raise ValueError('Database references missing media; backup is incomplete')
        progress(f'Database media references covered; backing up {len(media)} objects.')
        existing = {item['Key'] for item in list_objects(client, bucket, PREFIX + 'media/')}
        manifest['media'] = []
        # Four bounded I/O threads; no extra OCR/AI workers or memory-sized files.
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = pool.map(lambda item: backup_media(client, bucket, item, existing), media)
            for index, item in enumerate(results, 1):
                manifest['media'].append(item)
                if index % 20 == 0:
                    progress(f'Media backup verified: {index}/{len(media)} objects.')
        progress(f'Media backup verified: {len(media)}/{len(media)} objects.')
        db_key = snapshot_key + '/database.dump'
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        client.upload_file(str(archive), bucket, db_key)
        if object_hash(client, bucket, db_key) != digest:
            raise ValueError('Database backup readback hash mismatch')
        manifest['database'] = {'backup_key': db_key, 'sha256': digest, 'bytes': archive.stat().st_size}
        manifest['database_completed_at'] = datetime.now(timezone.utc).isoformat()
        manifest['media_completed_at'] = manifest['database_completed_at']
        manifest_key = snapshot_key + '/manifest.json'
        body = json.dumps(manifest, sort_keys=True).encode()
        client.put_object(Bucket=bucket, Key=manifest_key, Body=body, ContentType='application/json')
        # Publish the completion marker last; maintenance must never trust a partial run.
        with client.get_object(Bucket=bucket, Key=manifest_key)['Body'] as response:
            if response.read() != body:
                raise ValueError('Backup manifest readback mismatch')
        progress('Database and media snapshot completed.')
        return manifest_key, manifest


def prune_backups(client, bucket, now=None):
    """Keep 30 days. Only this command's namespace is eligible for deletion."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    objects = list_objects(client, bucket, PREFIX)
    manifests = [item for item in objects if re.fullmatch(
        re.escape(PREFIX) + r'snapshots/\d{8}T\d{6}Z-[0-9a-f]{32}/manifest\.json', item['Key'])]
    retained_media = set()
    expired_snapshots = set()
    for item in manifests:
        if item['LastModified'] < cutoff:
            expired_snapshots.add(item['Key'].rsplit('/', 1)[0] + '/')
        else:
            with client.get_object(Bucket=bucket, Key=item['Key'])['Body'] as body:
                manifest = json.load(body)
            retained_media.update(entry['backup_key'] for entry in manifest['media'])
    if not retained_media and not any(item['LastModified'] >= cutoff for item in manifests):
        raise ValueError('No recent completed backup; refusing retention cleanup')
    deleted = 0
    for item in objects:
        key = item['Key']
        if item['LastModified'] >= cutoff:
            continue
        expired_snapshot = any(key.startswith(prefix) for prefix in expired_snapshots)
        unused_media = key.startswith(PREFIX + 'media/') and key not in retained_media
        if expired_snapshot or unused_media:
            client.delete_object(Bucket=bucket, Key=key)
            deleted += 1
    return deleted
