"""Best-effort file metadata (size in bytes, page count) for resource files.

Nothing here raises: failures are logged and the affected value is None.
"""
import logging
import re
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_SLIDE_ENTRY = re.compile(r'^ppt/slides/slide\d+\.xml$')


def get_file_metadata(file_obj, name):
    """Return (size_bytes, page_count) for an open, seekable binary file."""
    size = _file_size(file_obj, name)
    page_count = None
    extension = Path(name or '').suffix.lower().lstrip('.')
    try:
        if extension == 'pdf':
            page_count = _pdf_page_count(file_obj)
        elif extension == 'docx':
            page_count = _office_app_count(file_obj, 'Pages')
        elif extension == 'pptx':
            try:
                page_count = _office_app_count(file_obj, 'Slides')
            except Exception as exc:
                logger.warning('Could not read app.xml slide count for %s: %s', name, exc)
            if page_count is None:
                page_count = _pptx_slide_entries(file_obj)
    except Exception as exc:
        logger.warning('Could not read page count for %s: %s', name, exc)
        page_count = None
    finally:
        _rewind(file_obj)
    return size, page_count


def _file_size(file_obj, name):
    try:
        size = getattr(file_obj, 'size', None)
        if size is None:
            position = file_obj.tell()
            file_obj.seek(0, 2)
            size = file_obj.tell()
            file_obj.seek(position)
        return int(size) if size is not None and int(size) >= 0 else None
    except Exception as exc:
        logger.warning('Could not read file size for %s: %s', name, exc)
        return None


def _rewind(file_obj):
    try:
        file_obj.seek(0)
    except Exception:
        pass


def _pdf_page_count(file_obj):
    import pypdfium2

    file_obj.seek(0)
    source = file_obj if hasattr(file_obj, 'readinto') else file_obj.read()
    document = pypdfium2.PdfDocument(source)
    try:
        return len(document) or None
    finally:
        document.close()


def _office_app_count(file_obj, tag):
    """Read <Pages>/<Slides> from docProps/app.xml (written by the authoring app)."""
    from xml.etree import ElementTree

    file_obj.seek(0)
    with zipfile.ZipFile(file_obj) as archive:
        try:
            xml = archive.read('docProps/app.xml')
        except KeyError:
            return None
    root = ElementTree.fromstring(xml)
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] == tag and element.text:
            value = int(element.text.strip())
            return value if value > 0 else None
    return None


def _pptx_slide_entries(file_obj):
    file_obj.seek(0)
    with zipfile.ZipFile(file_obj) as archive:
        count = sum(1 for entry in archive.namelist() if _SLIDE_ENTRY.match(entry))
    return count or None
