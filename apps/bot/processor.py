"""Bounded document extraction, called only by the worker subprocess."""
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass
class ExtractionResult:
    text: str
    outcome: str = 'complete'
    note: str = ''


def extract_document(file_path):
    suffix = Path(file_path).suffix.lower()
    if suffix == '.pdf':
        return extract_pdf(file_path)
    if suffix in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}:
        return ExtractionResult(extract_image(file_path))
    if suffix == '.docx':
        return ExtractionResult(extract_docx(file_path))
    return ExtractionResult('', 'skipped', f'Unsupported file type: {suffix or "unknown"}')


def extract_text(file_path):
    result = extract_document(file_path)
    if result.outcome == 'skipped' or not result.text.strip():
        raise ValueError(result.note or 'No text extracted; manual review required.')
    return result.text


def extract_pdf(file_path):
    import pdfplumber
    limit = settings.EXTRACTION_MAX_PAGES
    with pdfplumber.open(file_path) as pdf:
        if len(pdf.pages) > limit:
            return ExtractionResult('', 'skipped', f'PDF exceeds {limit} pages; manual review required.')
        texts = []
        image_only_pages = 0
        for page in pdf.pages:
            page_text = page.extract_text() or ''
            if not page_text.strip() and page.images:
                image_only_pages += 1
            texts.append(page_text)
            page.flush_cache()
    text = '\n'.join(texts).strip()
    if len(text) >= 50:
        if image_only_pages:
            return ExtractionResult(text, 'partial', f'{image_only_pages} image-only page(s) need OCR/manual review.')
        return ExtractionResult(text)
    return extract_pdf_with_ocr(file_path)


def extract_pdf_with_ocr(file_path):
    import pytesseract
    from pdf2image import convert_from_path, pdfinfo_from_path

    # An unreadable page count is an error. Never render an entire unknown PDF.
    count = int(pdfinfo_from_path(file_path, timeout=20)['Pages'])
    if not 0 < count <= settings.EXTRACTION_MAX_PAGES:
        return ExtractionResult('', 'skipped', 'PDF page limit exceeded; manual review required.')
    if Path(file_path).stat().st_size > settings.OCR_MAX_FILE_BYTES:
        return ExtractionResult('', 'skipped', 'Scanned PDF exceeds OCR size limit; manual review required.')
    deadline = time.monotonic() + settings.EXTRACTION_TIMEOUT_SECONDS
    texts = []
    skipped = 0
    for page in range(1, count + 1):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            skipped += count - page + 1
            break
        images = []
        try:
            images = convert_from_path(
                file_path, dpi=120, first_page=page, last_page=page, thread_count=1,
                grayscale=True, size=1800, timeout=min(30, remaining),
            )
            if not images:
                raise ValueError('No rendered page')
            remaining = deadline - time.monotonic()
            if remaining < 1:
                raise TimeoutError('Document deadline exceeded')
            texts.append(pytesseract.image_to_string(images[0], lang='eng', timeout=min(30, remaining)))
        except Exception:
            skipped += 1
        finally:
            for image in images:
                image.close()
    text = '\n'.join(texts).strip()
    if not text:
        return ExtractionResult('', 'empty', f'No OCR text extracted; {skipped} page(s) failed or skipped.')
    if skipped:
        return ExtractionResult(text, 'partial', f'{skipped} page(s) failed or skipped; review extracted text.')
    return ExtractionResult(text)


def extract_image(file_path):
    import pytesseract
    from PIL import Image
    with Image.open(file_path) as image:
        if image.width * image.height > 20000000:
            raise ValueError('Image exceeds 20 million pixels; manual review required.')
        image.thumbnail((1800, 1800))
        return pytesseract.image_to_string(image, lang='eng', timeout=30).strip()


def extract_docx(file_path):
    import docx
    document = docx.Document(file_path)
    return '\n'.join(paragraph.text for paragraph in document.paragraphs if paragraph.text).strip()
