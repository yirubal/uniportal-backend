import os
import tempfile
from pathlib import Path


def safe_filename(filename):
    return Path(str(filename).replace('\\', '/')).name[:240] or 'document'


async def download_file(bot, file_id, filename):
    """Return a unique temporary path; the caller removes it in finally."""
    suffix = Path(safe_filename(filename)).suffix
    descriptor, path = tempfile.mkstemp(prefix='uniportal-telegram-', suffix=suffix)
    os.close(descriptor)
    try:
        file = await bot.get_file(file_id)
        await file.download_to_drive(path)
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
