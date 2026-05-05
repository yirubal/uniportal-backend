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
    """
    Points the resource directly at the inbox file path in R2.
    No download, no upload, no copy — instant regardless of file size.

    The file stays at its inbox/ path in R2. The resource.file field
    is set to that same key. clear_inbox_file will only clear the DB
    reference (not delete the file) since the resource is using it.
    """
    if not inbox_item.file or not inbox_item.file.name:
        raise FileNotFoundError('Inbox item has no file.')

    resource.file.name = inbox_item.file.name
    return resource


def clear_inbox_file(inbox_item, *, protected_file_name=None):
    """
    Clears the inbox file reference.
    If the inbox file path matches the protected_file_name (i.e. the
    resource is using the same file), only the DB reference is cleared —
    the actual R2 file is preserved.
    """
    file_name = inbox_item.file.name
    if not file_name:
        return False

    if protected_file_name and file_name == protected_file_name:
        # Resource is using this file — only clear DB reference
        inbox_item.file.name = ''
        inbox_item.save(update_fields=['file'])
        return True

    # Different file — delete from R2 and clear reference
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
    """
    Cleans up any legacy inbox items that still have a separate file
    from before the no-copy approach was introduced.
    """
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
            # Same path — just clear inbox DB reference, keep the file
            stats['skipped_same_file'] += 1
            if not dry_run:
                inbox_item.file.name = ''
                inbox_item.save(update_fields=['file'])
            messages.append(
                f'Cleared shared-path inbox reference for inbox {inbox_item.id}'
            )
            continue

        if not storage_file_exists(inbox_item.file):
            stats['skipped_missing_inbox_file'] += 1
            if not dry_run:
                inbox_item.file.name = ''
                inbox_item.save(update_fields=['file'])
            messages.append(
                f'Cleared missing inbox file reference for inbox {inbox_item.id}'
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