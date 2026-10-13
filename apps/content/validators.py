"""Upload bounds and basic format checks; client MIME labels are not trusted."""
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'csv',
                      'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff'}


def validate_document_upload(file, *, pdf_only=False):
    if not file:
        return
    # Unchanged stored files do not need a network read during an admin edit.
    if getattr(file, '_committed', False):
        return
    limit = settings.MAX_EXAM_PDF_UPLOAD_BYTES if pdf_only else settings.MAX_DOCUMENT_UPLOAD_BYTES
    if file.size <= 0 or file.size > limit:
        raise ValidationError(f'File must contain 1–{limit // (1024 * 1024)} MiB of data.')
    suffix = Path(file.name).suffix.lower().lstrip('.')
    if suffix not in ({'pdf'} if pdf_only else ALLOWED_EXTENSIONS):
        raise ValidationError('Unsupported file extension.')
    position = file.tell()
    try:
        file.seek(0)
        header = file.read(32)
        signatures = {
            'pdf': (b'%PDF',), 'png': (b'\x89PNG\r\n\x1a\n',),
            'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',),
            'gif': (b'GIF87a', b'GIF89a'), 'bmp': (b'BM',),
            'tif': (b'II*\x00', b'MM\x00*'), 'tiff': (b'II*\x00', b'MM\x00*'),
            'doc': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
            'xls': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
            'ppt': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
        }
        if suffix in signatures and not header.startswith(signatures[suffix]):
            raise ValidationError('File contents do not match the extension.')
        if suffix == 'webp' and not (header.startswith(b'RIFF') and header[8:12] == b'WEBP'):
            raise ValidationError('Invalid WebP file.')
        if suffix in {'docx', 'pptx', 'xlsx'}:
            file.seek(0)
            try:
                with ZipFile(file) as archive:
                    names = set(archive.namelist())
                    required = {'docx': 'word/document.xml', 'pptx': 'ppt/presentation.xml', 'xlsx': 'xl/workbook.xml'}[suffix]
                    if required not in names or '[Content_Types].xml' not in names:
                        raise ValidationError('Invalid Office document.')
            except BadZipFile as exc:
                raise ValidationError('Invalid Office document.') from exc
        if suffix in {'txt', 'csv'} and b'\x00' in header:
            raise ValidationError('Invalid text file.')
    finally:
        file.seek(position)


def validate_exam_pdf(file):
    validate_document_upload(file, pdf_only=True)
