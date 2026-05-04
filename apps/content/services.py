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


def _r2_server_side_copy(source_field_file, dest_field_file, dest_filename):
    try:
        from django.utils import timezone

        storage = source_field_file.storage
        if not hasattr(storage, 'bucket_name'):
            return None

        bucket_name = storage.bucket_name
        source_key  = source_field_file.name

        now      = timezone.now()
        dest_key = f'resources/{now.year}/{now.month:02d}/{dest_filename}'

        # Reuse the storage's existing client — no new connection
        client = storage.connection.meta.client
        client.copy(
            CopySource={'Bucket': bucket_name, 'Key': source_key},
            Bucket=bucket_name,
            Key=dest_key,
        )

        return dest_key

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f'R2 server-side copy failed, falling back to stream copy: {e}'
        )
        return None
        
    """
    Uses boto3 server-side copy to copy a file within R2 without
    downloading or re-uploading it. Near-instant for any file size.

    Returns the new file name (key) on success, or None if not applicable.
    """
    try:
        import boto3
        from django.conf import settings

        storage = source_field_file.storage

        # Only works with S3/R2 storage backends
        if not hasattr(storage, 'bucket_name'):
            return None

        bucket_name = storage.bucket_name
        source_key  = source_field_file.name

        # Build destination key under resources/
        from django.utils import timezone
        now = timezone.now()
        dest_key = f'resources/{now.year}/{now.month:02d}/{dest_filename}'

        # Use the storage's own connection
        s3 = storage.connection
        s3.meta.client.copy(
            CopySource={'Bucket': bucket_name, 'Key': source_key},
            Bucket=bucket_name,
            Key=dest_key,
        )

        return dest_key

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f'R2 server-side copy failed, falling back to stream copy: {e}'
        )
        return None


def copy_inbox_file_to_resource(inbox_item, resource):
    """
    Copies the inbox file to the resource.
    Tries R2 server-side copy first (fast, no download).
    Falls back to stream copy if server-side copy is unavailable.
    """
    filename = Path(inbox_item.original_filename or inbox_item.file.name).name

    # Try fast server-side copy first
    dest_key = _r2_server_side_copy(inbox_item.file, resource.file, filename)
    if dest_key:
        # Point resource.file at the new key without uploading
        resource.file.name = dest_key
        return resource

    # Fallback: stream copy (download + re-upload)
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


def storage_file_exists(field_file):
    if not field_file or not field_file.name:
        return False
    try:
        return field_file.storage.exists(field_file.name)
    except Exception:
        return False


def cleanup_assigned_inbox_duplicates(*, dry_run=False, limit=None):
    stats = {
        'checked': 0,
        'cleaned': 0,
        'skipped_missing_resource_file': 0,
        'skipped_missing_inbox_file': 0,
        'skipped_same_file': 0,
        'failed': 0,
    }
    messages = []

    queryset = FileInbox.objects.select_related('assigned_resource').filter(
        assigned_resource__isnull=False,
    ).exclude(file='')
    if limit:
        queryset = queryset[:limit]

    for inbox_item in queryset:
        stats['checked'] += 1
        resource = inbox_item.assigned_resource

        if not storage_file_exists(resource.file):
            stats['skipped_missing_resource_file'] += 1
            messages.append(
                f'Skipped inbox {inbox_item.id}; resource file missing for resource {resource.id}'
            )
            continue

        if inbox_item.file.name == resource.file.name:
            stats['skipped_same_file'] += 1
            messages.append(
                f'Skipped inbox {inbox_item.id}; inbox and resource use the same file'
            )
            continue

        if not storage_file_exists(inbox_item.file):
            stats['skipped_missing_inbox_file'] += 1
            inbox_item.file.name = ''
            if not dry_run:
                inbox_item.save(update_fields=['file'])
            messages.append(
                (
                    f'Would clear missing inbox file reference for inbox {inbox_item.id}'
                    if dry_run
                    else f'Cleared missing inbox file reference for inbox {inbox_item.id}'
                )
            )
            continue

        if dry_run:
            stats['cleaned'] += 1
            messages.append(
                f'Would delete duplicate inbox file for inbox {inbox_item.id}: {inbox_item.file.name}'
            )
            continue

        try:
            if clear_inbox_file(
                inbox_item,
                protected_file_name=resource.file.name,
            ):
                stats['cleaned'] += 1
                messages.append(
                    f'Deleted duplicate inbox file for inbox {inbox_item.id}'
                )
        except Exception as exc:
            stats['failed'] += 1
            messages.append(
                f'Failed to clean inbox {inbox_item.id}: {exc}'
            )

    return stats, messages