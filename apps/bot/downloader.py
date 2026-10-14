import os
import tempfile
from pathlib import Path
from django.conf import settings


def safe_filename(filename):
    return Path(str(filename).replace('\\', '/')).name[:240] or 'document'


async def download_file(bot, file_id, filename):
    """Return a unique temporary path; the caller removes it in finally."""
    suffix = Path(safe_filename(filename)).suffix
    descriptor, path = tempfile.mkstemp(prefix='uniportal-telegram-', suffix=suffix)
    os.close(descriptor)
    try:
        file = await bot.get_file(file_id)
        if getattr(file, 'file_size', None) and file.file_size > settings.MAX_DOCUMENT_UPLOAD_BYTES:
            raise ValueError('Telegram file exceeds the document size limit.')
        await file.download_to_drive(path)
        if Path(path).stat().st_size > settings.MAX_DOCUMENT_UPLOAD_BYTES:
            raise ValueError('Downloaded file exceeds the document size limit.')
        return path
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def get_file_info(message):
    if message.document:
        return message.document.file_id, safe_filename(message.document.file_name or f'document_{message.message_id}')
    if message.photo:
        return message.photo[-1].file_id, f'photo_{message.message_id}.jpg'
    return None, None
