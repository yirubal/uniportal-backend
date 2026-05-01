import logging
import os
import tempfile
from pathlib import Path

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


def _extract_inbox_text(inbox_item):
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
        with tempfile.NamedTemporaryFile(suffix=suffix) as temp_file:
            for chunk in inbox_item.file.chunks():
                temp_file.write(chunk)
            temp_file.flush()
            return extract_text(temp_file.name)
    finally:
        inbox_item.file.close()


async def process_inbox_item(inbox_id: int):
    """
    Processes a FileInbox item:
    - Extracts text from the file
    - Updates the inbox record with extracted text
    - Sets status to processed or failed
    """
    from apps.content.models import FileInbox

    try:
        # Get inbox item
        inbox_item = await sync_to_async(FileInbox.objects.get)(id=inbox_id)

        # Update status to processing
        inbox_item.processing_status = FileInbox.STATUS_PROCESSING
        await sync_to_async(inbox_item.save)()

        # Extract text
        extracted_text = await sync_to_async(_extract_inbox_text)(inbox_item)

        # Update inbox item
        inbox_item.extracted_text = extracted_text
        inbox_item.processing_status = FileInbox.STATUS_PROCESSED
        inbox_item.processing_error = ''
        await sync_to_async(inbox_item.save)()

        logger.info(f'Successfully processed inbox item {inbox_id}')

    except Exception as e:
        logger.error(f'Failed to process inbox item {inbox_id}: {e}')
        try:
            inbox_item = await sync_to_async(FileInbox.objects.get)(id=inbox_id)
            inbox_item.processing_status = FileInbox.STATUS_FAILED
            inbox_item.processing_error = str(e)
            await sync_to_async(inbox_item.save)()
        except Exception:
            pass
