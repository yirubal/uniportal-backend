"""Kill/restart drill on a disposable local PostgreSQL database; no external calls."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

ROOT = Path(__file__).resolve().parent.parent

# Run in a real child process with mocked external work. The ready marker is
# written through PostgreSQL so the parent knows the child entered processing.
CHILD = '''
import asyncio
import sys
import django
django.setup()
from unittest.mock import patch
from apps.bot.models import TelegramUpdate
from apps.bot.worker import process_claimed_work
from django.test import override_settings
from asgiref.sync import sync_to_async
pk, token, pause = sys.argv[1:]
if pause == 'inbox':
    import os
    with override_settings(MEDIA_ROOT=os.environ['DRILL_MEDIA_ROOT']):
        process_claimed_work('inbox', int(pk), token)
    sys.exit(0)
async def handle(payload):
    await sync_to_async(TelegramUpdate.objects.filter(pk=pk).update)(payload={'ready': True})
    if pause == 'yes':
        await asyncio.sleep(60)
with patch('apps.bot.application.process_telegram_update', side_effect=handle):
    process_claimed_work('update', int(pk), token)
'''

DRILL = '''
from datetime import timedelta
import os
import signal
import subprocess
import sys
import time
from django.utils import timezone
from django.db import connections
from apps.bot.models import TelegramUpdate, NotificationDelivery
from apps.bot.worker import claim_work, recover_stale_claims, run_claimed_subprocess
record = TelegramUpdate.objects.create(update_id=9876, payload={'update_id': 9876})
first = claim_work('update')
child = subprocess.Popen([sys.executable, '-c', os.environ['DRILL_CHILD'], str(first[0]), str(first[1]), 'yes'], start_new_session=True)
try:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        record.refresh_from_db()
        if record.payload.get('ready'):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('Child never reached processing')
    os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=5)
    record.refresh_from_db()
    assert record.status == 'processing'
    assert recover_stale_claims('update') == 0, 'Fresh claim was incorrectly recovered'
    TelegramUpdate.objects.filter(pk=record.pk).update(claimed_at=timezone.now() - timedelta(minutes=16))
    assert recover_stale_claims('update') == 1
    TelegramUpdate.objects.filter(pk=record.pk).update(next_attempt_at=timezone.now())
    second = claim_work('update')
    assert second[1] != first[1]
    subprocess.run([sys.executable, '-c', os.environ['DRILL_CHILD'], str(second[0]), str(second[1]), 'no'], check=True, timeout=15)
    record.refresh_from_db()
    assert record.status == 'processed' and record.attempt_count == 2
    assert TelegramUpdate.objects.count() == 1
    # Exercise the actual management-command subprocess boundary too. Test
    # settings blank the token: the delivery must persist and schedule a retry.
    delivery = NotificationDelivery.objects.create(chat_id=1, text='Synthetic drill', deduplication_key='drill')
    run_claimed_subprocess('notification', *claim_work('notification'))
    delivery.refresh_from_db()
    assert delivery.status == 'pending' and delivery.attempt_count == 1
    import shutil
    if shutil.which('tesseract'):
        # Real image OCR in a separate process, using only synthetic local media.
        from io import BytesIO
        from tempfile import TemporaryDirectory
        from PIL import Image, ImageDraw, ImageFont
        from django.core.files.base import ContentFile
        from django.test import override_settings
        from apps.content.models import FileInbox
        with TemporaryDirectory(prefix='uniportal-worker-media-') as media:
            image = Image.new('RGB', (700, 120), 'white')
            ImageDraw.Draw(image).text((20, 30), 'UNI PORTAL WORKER', font=ImageFont.load_default(size=40), fill='black')
            output = BytesIO()
            image.save(output, format='PNG')
            with override_settings(MEDIA_ROOT=media):
                inbox = FileInbox.objects.create(telegram_message_id=1234, original_filename='synthetic.png', posted_date=timezone.now())
                inbox.file.save('synthetic.png', ContentFile(output.getvalue()))
                claimed = claim_work('inbox')
                child_env = {**os.environ, 'DRILL_MEDIA_ROOT': media}
                subprocess.run([sys.executable, '-c', os.environ['DRILL_CHILD'], str(claimed[0]), str(claimed[1]), 'inbox'], env=child_env, check=True, timeout=30)
                inbox.refresh_from_db()
                assert inbox.processing_status == 'processed', inbox.processing_error
                assert 'WORKER' in inbox.extracted_text.upper(), inbox.extracted_text
        print('Real image OCR smoke check passed in worker child.')
    elif os.environ.get('DRILL_REQUIRE_OCR') == '1':
        raise RuntimeError('Install tesseract-ocr to run the required OCR smoke check.')
    else:
        print('OCR smoke check skipped: tesseract is not installed locally; CI requires it.')
    connections.close_all()
finally:
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
print('Worker recovery drill passed: interrupted claim retained, fresh claim protected, stale claim retried, replacement child completed once, delivery retry persisted.')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-ocr', action='store_true')
    options = parser.parse_args()
    supplied = os.environ.get('DATABASE_URL', '')
    parsed = urlsplit(supplied)
    if parsed.scheme not in {'postgres', 'postgresql'}:
        raise SystemExit('Use a disposable local PostgreSQL DATABASE_URL.')
    host = parse_dsn(supplied).get('host', '')
    if not (host in {'localhost', '127.0.0.1', '::1'} or host.startswith('/')):
        raise SystemExit('Remote PostgreSQL servers are refused.')
    name = 'uniportal_worker_drill_' + uuid4().hex[:12]
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query) if key != 'dbname'])
    url = f'{parsed.scheme}://{parsed.netloc}/{name}' + ('?' + query if query else '')
    admin = psycopg2.connect(supplied)
    admin.autocommit = True
    created = False
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
        env = {**os.environ, 'DATABASE_URL': url, 'DJANGO_SETTINGS_MODULE': 'config.settings.test', 'DRILL_CHILD': CHILD, 'DRILL_REQUIRE_OCR': '1' if options.require_ocr else '0'}
        subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=ROOT, env=env,
                       check=True, timeout=60, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, 'manage.py', 'shell', '--command', DRILL], cwd=ROOT, env=env,
                       check=True, timeout=45)
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__ == '__main__':
    main()
