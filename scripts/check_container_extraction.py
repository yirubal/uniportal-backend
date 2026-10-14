"""Synthetic image/scanned-PDF smoke check; no database or external API calls.

Run inside the built image with DJANGO_SETTINGS_MODULE=config.settings.test and
READ_DOT_ENV=False. Files are created only in a temporary directory.
"""
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test')
os.environ.setdefault('READ_DOT_ENV', 'False')

import django

django.setup()

from PIL import Image, ImageDraw, ImageFont
import pypdfium2

from apps.bot.processor import extract_document


def main():
    for executable in ('tesseract', 'pdftoppm', 'pdfinfo'):
        if not shutil.which(executable):
            raise RuntimeError(f'Required extraction tool missing: {executable}')
    with TemporaryDirectory(prefix='uniportal-extraction-smoke-') as directory:
        image_path = Path(directory) / 'synthetic.png'
        pdf_path = Path(directory) / 'synthetic-scanned.pdf'
        with Image.new('RGB', (1200, 180), 'white') as image:
            ImageDraw.Draw(image).text(
                (30, 45), 'UNI PORTAL WORKER',
                font=ImageFont.load_default(size=48), fill='black',
            )
            image.save(image_path)
            image.save(pdf_path, format='PDF', resolution=120)
        # Load the native PDFium library too, without invoking OCR or any API.
        with pypdfium2.PdfDocument(pdf_path) as document:
            if len(document) != 1:
                raise RuntimeError('Synthetic PDF should contain exactly one page.')
        for path in (image_path, pdf_path):
            result = extract_document(str(path))
            if result.outcome != 'complete' or 'WORKER' not in result.text.upper():
                raise RuntimeError(f'{path.suffix} extraction did not recover the synthetic text.')
            print(f'{path.suffix} real OCR passed; complete synthetic text recovered.')
    print('Container extraction smoke passed: PDFium, Pillow, Tesseract and Poppler.')


if __name__ == '__main__':
    main()
