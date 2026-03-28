import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'

        # If pdfplumber got meaningful text return it
        if len(text.strip()) > 50:
            logger.info(f'Extracted PDF text using pdfplumber: {file_path}')
            return text.strip()

        # Otherwise fall back to OCR
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
    Used for scanned exam papers.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(file_path, dpi=200)
        text = ''
        for i, image in enumerate(images):
            page_text = pytesseract.image_to_string(image, lang='eng')
            text += page_text + '\n'
            logger.info(f'OCR processed page {i + 1} of {file_path}')

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
    Used for photos of exam papers or handwritten notes.
    """
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(file_path)
        text = pytesseract.image_to_string(image, lang='eng')
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