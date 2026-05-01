from pathlib import Path

from django.core.files import File

from .models import FileInbox


def create_inbox_item_from_local_file(
    *,
    file_path,
    original_filename,
    telegram_message_id,
    telegram_caption,
    posted_date,
    processing_status=FileInbox.STATUS_UNPROCESSED,
    processing_error='',
):
    inbox_item = FileInbox(
        original_filename=original_filename,
        telegram_message_id=telegram_message_id,
        telegram_caption=telegram_caption,
        posted_date=posted_date,
        processing_status=processing_status,
        processing_error=processing_error,
    )
    return save_local_file_to_inbox_item(
        inbox_item,
        file_path=file_path,
        original_filename=original_filename,
        telegram_caption=telegram_caption,
        posted_date=posted_date,
        processing_status=processing_status,
        processing_error=processing_error,
    )


def save_local_file_to_inbox_item(
    inbox_item,
    *,
    file_path,
    original_filename,
    telegram_caption,
    posted_date,
    processing_status=FileInbox.STATUS_UNPROCESSED,
    processing_error='',
):
    inbox_item.original_filename = original_filename
    inbox_item.telegram_caption = telegram_caption
    inbox_item.posted_date = posted_date
    inbox_item.processing_status = processing_status
    inbox_item.processing_error = processing_error
    with open(file_path, 'rb') as handle:
        inbox_item.file.save(
            Path(original_filename).name,
            File(handle),
            save=False,
        )
    inbox_item.save()
    return inbox_item


def copy_inbox_file_to_resource(inbox_item, resource):
    filename = Path(inbox_item.original_filename or inbox_item.file.name).name
    inbox_item.file.open('rb')
    try:
        resource.file.save(
            filename,
            File(inbox_item.file),
            save=False,
        )
    finally:
        inbox_item.file.close()
    return resource


def clear_inbox_file(inbox_item, *, protected_file_name=None):
    file_name = inbox_item.file.name
    if not file_name:
        return False

    if protected_file_name and file_name == protected_file_name:
        return False

    storage = inbox_item.file.storage
    if storage.exists(file_name):
        storage.delete(file_name)

    inbox_item.file.name = ''
    inbox_item.save(update_fields=['file'])
    return True
