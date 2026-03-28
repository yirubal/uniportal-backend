import logging
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


async def process_inbox_item(inbox_id: int):
    """
    Processes a FileInbox item:
    - Extracts text from the file
    - Updates the inbox record with extracted text
    - Sets status to processed or failed
    """
    from apps.content.models import FileInbox
    from .processor import extract_text
    from django.conf import settings
    import os

    try:
        # Get inbox item
        inbox_item = await sync_to_async(FileInbox.objects.get)(id=inbox_id)

        # Update status to processing
        inbox_item.processing_status = FileInbox.STATUS_PROCESSING
        await sync_to_async(inbox_item.save)()

        # Build full file path
        file_path = os.path.join(settings.MEDIA_ROOT, str(inbox_item.file))

        if not os.path.exists(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')

        # Extract text
        extracted_text = await sync_to_async(extract_text)(file_path)

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