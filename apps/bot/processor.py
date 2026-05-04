import gc
import os
import logging
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

# Max seconds to spend on a single OCR page before skipping it
OCR_PAGE_TIMEOUT_SECONDS = 60


class PageTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise PageTimeoutError('OCR page timed out')


def extract_text(file_path: str) -> str:
    """
    Routes file to correct extractor based on file extension.
    Returns extracted text string or empty string if extraction fails.
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == '.pdf':
        return extract_pdf(file_path)
    elif extension in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']:
        return extract_image(file_path)
    elif extension in ['.docx', '.doc']:
        return extract_docx(file_path)
    else:
        logger.warning(f'Unsupported file type: {extension}')
        return ''


def extract_pdf(file_path: str) -> str:
    """
    Extracts text from PDF files.
    Tries pdfplumber first (digital PDFs).
    Falls back to pytesseract OCR (scanned PDFs).
    """
    try:
        import pdfplumber
        text = ''
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f'PDF has {total_pages} pages: {file_path}')
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
                # Free page memory immediately
                del page
                gc.collect()

        if len(text.strip()) > 50:
            logger.info(f'Extracted PDF text using pdfplumber ({len(text)} chars): {file_path}')
            return text.strip()

        logger.info(f'PDF appears scanned, falling back to OCR: {file_path}')
        return extract_pdf_with_ocr(file_path)

    except ImportError:
        logger.warning('pdfplumber not installed, falling back to OCR')
        return extract_pdf_with_ocr(file_path)
    except Exception as e:
        logger.error(f'PDF extraction failed for {file_path}: {e}')
        return extract_pdf_with_ocr(file_path)


def extract_pdf_with_ocr(file_path: str) -> str:
    """
    Converts each PDF page to an image then runs OCR on it.
    Each page has a timeout of OCR_PAGE_TIMEOUT_SECONDS.
    Pages that time out are skipped with a placeholder.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path

        text = ''
        skipped = 0

        # Convert one page at a time to limit memory usage
        # first_page/last_page args let us process page by page
        try:
            # Get total page count first
            from pdf2image import pdfinfo_from_path
            info = pdfinfo_from_path(file_path)
            total_pages = info.get('Pages', 1)
        except Exception:
            # If pdfinfo fails, convert all at once (fallback)
            total_pages = None

        if total_pages:
            logger.info(f'OCR: processing {total_pages} pages one by one: {file_path}')
            for page_num in range(1, total_pages + 1):
                try:
                    images = convert_from_path(
                        file_path,
                        dpi=150,
                        first_page=page_num,
                        last_page=page_num,
                    )
                    if not images:
                        continue
                    image = images[0]

                    # Set per-page timeout using SIGALRM (Unix only)
                    try:
                        signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(OCR_PAGE_TIMEOUT_SECONDS)
                        page_text = pytesseract.image_to_string(image, lang='eng')
                        signal.alarm(0)  # Cancel alarm
                    except PageTimeoutError:
                        signal.alarm(0)
                        logger.warning(f'OCR timeout on page {page_num} of {file_path} — skipping')
                        text += f'\n[Page {page_num}: OCR timed out — skipped]\n'
                        skipped += 1
                        continue

                    text += page_text + '\n'
                    logger.info(f'OCR processed page {page_num}/{total_pages}')

                    del image
                    del images
                    gc.collect()

                except Exception as e:
                    logger.warning(f'OCR failed on page {page_num}: {e} — skipping')
                    text += f'\n[Page {page_num}: OCR failed — skipped]\n'
                    skipped += 1
                    continue
        else:
            # Fallback: convert all pages at once
            images = convert_from_path(file_path, dpi=150)
            for i, image in enumerate(images):
                try:
                    signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.alarm(OCR_PAGE_TIMEOUT_SECONDS)
                    page_text = pytesseract.image_to_string(image, lang='eng')
                    signal.alarm(0)
                    text += page_text + '\n'
                    logger.info(f'OCR processed page {i + 1}')
                except PageTimeoutError:
                    signal.alarm(0)
                    logger.warning(f'OCR timeout on page {i + 1} — skipping')
                    text += f'\n[Page {i + 1}: OCR timed out — skipped]\n'
                    skipped += 1
                finally:
                    del image
                    gc.collect()
            del images
            gc.collect()

        if skipped:
            logger.warning(f'OCR complete with {skipped} skipped pages: {file_path}')
        else:
            logger.info(f'OCR complete, all pages processed: {file_path}')

        return text.strip()

    except ImportError:
        logger.error('pytesseract or pdf2image not installed')
        return ''
    except Exception as e:
        logger.error(f'OCR extraction failed for {file_path}: {e}')
        return ''


def extract_image(file_path: str) -> str:
    """
    Extracts text from image files using pytesseract OCR.
    """
    try:
        import pytesseract
        from PIL import Image

        with Image.open(file_path) as image:
            try:
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(OCR_PAGE_TIMEOUT_SECONDS)
                text = pytesseract.image_to_string(image, lang='eng')
                signal.alarm(0)
            except PageTimeoutError:
                signal.alarm(0)
                logger.warning(f'OCR timeout on image: {file_path}')
                return ''

        gc.collect()
        logger.info(f'Extracted image text using OCR: {file_path}')
        return text.strip()

    except ImportError:
        logger.error('pytesseract or Pillow not installed')
        return ''
    except Exception as e:
        logger.error(f'Image extraction failed for {file_path}: {e}')
        return ''


def extract_docx(file_path: str) -> str:
    """
    Extracts text from Word documents.
    """
    try:
        import docx
        doc = docx.Document(file_path)
        text = '\n'.join([para.text for para in doc.paragraphs if para.text])
        logger.info(f'Extracted docx text: {file_path}')
        return text.strip()
    except ImportError:
        logger.error('python-docx not installed')
        return ''
    except Exception as e:
        logger.error(f'Docx extraction failed for {file_path}: {e}')
        return ''