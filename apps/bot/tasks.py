import logging
import os
import tempfile
from pathlib import Path
from asgiref.sync import sync_to_async
from django.core.cache import cache

logger = logging.getLogger(__name__)

INBOX_DUPLICATE_CLEANUP_CACHE_KEY = 'content:assigned-inbox-duplicate-cleanup'
INBOX_DUPLICATE_CLEANUP_INTERVAL_SECONDS = 5 * 60
INBOX_DUPLICATE_CLEANUP_LIMIT = 100


# ── Stuck item recovery ───────────────────────────────────────────────────────

def recover_stuck_inbox_items():
    """
    Resets any FileInbox items stuck in STATUS_PROCESSING back to
    STATUS_UNPROCESSED so they get retried on the next file event.

    Call this once on bot startup.
    """
    from apps.content.models import FileInbox
    stuck = FileInbox.objects.filter(processing_status=FileInbox.STATUS_PROCESSING)
    count = stuck.count()
    if count:
        stuck.update(processing_status=FileInbox.STATUS_UNPROCESSED)
        logger.warning(f'Recovered {count} stuck inbox item(s) → unprocessed')
    else:
        logger.info('No stuck inbox items found.')


def recover_failed_inbox_items():
    """
    Resets FileInbox items in STATUS_FAILED back to STATUS_UNPROCESSED
    so they get retried. Call this once on bot startup.
    """
    from apps.content.models import FileInbox
    failed = FileInbox.objects.filter(
        processing_status=FileInbox.STATUS_FAILED,
        assigned_resource__isnull=True,
    )
    count = failed.count()
    if count:
        failed.update(
            processing_status=FileInbox.STATUS_UNPROCESSED,
            processing_error='',
        )
        logger.warning(f'Reset {count} failed inbox item(s) → unprocessed for retry')


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_inbox_text(inbox_item):
    from django.conf import settings
    from .processor import extract_text
    import os

    # Skip OCR for files larger than limit to prevent memory crash
    max_mb = int(os.environ.get('MAX_OCR_FILE_SIZE_MB', 5))
    try:
        file_size_mb = inbox_item.file.size / (1024 * 1024)
        if file_size_mb > max_mb:
            logger.warning(
                f'File {inbox_item.original_filename} is {file_size_mb:.1f}MB '
                f'— skipping OCR (limit {max_mb}MB), saving without text extraction.'
            )
            return f'[Text extraction skipped — file too large ({file_size_mb:.1f}MB)]'
    except Exception:
        pass

    local_path = os.path.join(settings.MEDIA_ROOT, str(inbox_item.file))
    if os.path.exists(local_path):
        return extract_text(local_path)

    if not inbox_item.file:
        raise FileNotFoundError('Inbox item has no file.')

    suffix = Path(inbox_item.file.name).suffix
    inbox_item.file.open('rb')
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            for chunk in inbox_item.file.chunks():
                temp_file.write(chunk)
            temp_file.flush()
        return extract_text(temp_path)
    finally:
        inbox_item.file.close()
        try:
            os.unlink(temp_path)
        except Exception:
            pass
            
    from django.conf import settings
    from .processor import extract_text

    local_path = os.path.join(settings.MEDIA_ROOT, str(inbox_item.file))
    if os.path.exists(local_path):
        return extract_text(local_path)

    if not inbox_item.file:
        raise FileNotFoundError('Inbox item has no file.')

    suffix = Path(inbox_item.file.name).suffix
    inbox_item.file.open('rb')
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            for chunk in inbox_item.file.chunks():
                temp_file.write(chunk)
            temp_file.flush()
        return extract_text(temp_path)
    finally:
        inbox_item.file.close()
        try:
            os.unlink(temp_path)
        except Exception:
            pass


# ── Duplicate cleanup ─────────────────────────────────────────────────────────

def _cleanup_assigned_inbox_duplicates_if_due():
    if cache.get(INBOX_DUPLICATE_CLEANUP_CACHE_KEY):
        return
    from apps.content.services import cleanup_assigned_inbox_duplicates
    cache.set(
        INBOX_DUPLICATE_CLEANUP_CACHE_KEY,
        True,
        INBOX_DUPLICATE_CLEANUP_INTERVAL_SECONDS,
    )
    stats, _ = cleanup_assigned_inbox_duplicates(
        limit=INBOX_DUPLICATE_CLEANUP_LIMIT,
    )
    if stats['cleaned'] or stats['failed']:
        logger.info(
            'Assigned inbox duplicate cleanup checked=%s cleaned=%s failed=%s',
            stats['checked'],
            stats['cleaned'],
            stats['failed'],
        )


# ── Main processing task ──────────────────────────────────────────────────────

async def process_inbox_item(inbox_id: int):
    """
    Processes a FileInbox item:
    - Extracts text from the file (with timeout protection)
    - Updates the inbox record with extracted text
    - Sets status to processed or failed
    """
    from apps.content.models import FileInbox

    try:
        inbox_item = await sync_to_async(FileInbox.objects.get)(id=inbox_id)
        await sync_to_async(_cleanup_assigned_inbox_duplicates_if_due)()

        inbox_item.processing_status = FileInbox.STATUS_PROCESSING
        await sync_to_async(inbox_item.save)()

        logger.info(f'Processing inbox item {inbox_id}: {inbox_item.original_filename}')

        # Run extraction — this can take a while for large PDFs
        extracted_text = await sync_to_async(_extract_inbox_text)(inbox_item)

        inbox_item.extracted_text = extracted_text
        inbox_item.processing_status = FileInbox.STATUS_PROCESSED
        inbox_item.processing_error = ''
        await sync_to_async(inbox_item.save)()

        logger.info(
            f'Successfully processed inbox item {inbox_id} '
            f'({len(extracted_text)} chars extracted)'
        )

    except Exception as e:
        logger.error(f'Failed to process inbox item {inbox_id}: {e}')
        try:
            inbox_item = await sync_to_async(FileInbox.objects.get)(id=inbox_id)
            inbox_item.processing_status = FileInbox.STATUS_FAILED
            inbox_item.processing_error = str(e)
            await sync_to_async(inbox_item.save)()
        except Exception:
            pass