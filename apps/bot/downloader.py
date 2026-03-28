import os
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

# Where downloaded files are saved
INBOX_DIR = Path(settings.MEDIA_ROOT) / 'inbox'


def ensure_inbox_dir():
    """Create inbox directory if it doesn't exist."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)


async def download_file(bot, file_id: str, filename: str) -> str | None:
    """
    Downloads a file from Telegram and saves it to the inbox directory.
    Returns the full file path if successful, None if failed.
    """
    try:
        ensure_inbox_dir()

        # Get file info from Telegram
        file = await bot.get_file(file_id)

        # Build save path
        save_path = INBOX_DIR / filename

        # Handle duplicate filenames
        counter = 1
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        while save_path.exists():
            save_path = INBOX_DIR / f'{stem}_{counter}{suffix}'
            counter += 1

        # Download the file
        await file.download_to_drive(str(save_path))

        logger.info(f'Downloaded file: {save_path}')
        return str(save_path)

    except Exception as e:
        logger.error(f'Failed to download file {filename}: {e}')
        return None


def get_file_info(message) -> tuple[str, str] | tuple[None, None]:
    """
    Extracts file_id and filename from a Telegram message.
    Handles documents, photos.
    Returns (file_id, filename) or (None, None) if no file.
    """
    if message.document:
        file_id = message.document.file_id
        filename = message.document.file_name or f'document_{message.message_id}'
        return file_id, filename

    if message.photo:
        # Photos come as multiple sizes — get the largest
        photo = message.photo[-1]
        file_id = photo.file_id
        filename = f'photo_{message.message_id}.jpg'
        return file_id, filename

    return None, None