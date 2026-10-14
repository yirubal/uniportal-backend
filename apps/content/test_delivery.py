from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from storages.backends.s3 import S3Storage

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.bot.models import TelegramUpdate
from apps.exams.models import ExamPDFUpload
from .models import Resource, FileInbox
from .delivery import resource_file_url
from .validators import validate_document_upload, validate_exam_pdf


class FileDeliveryTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(telegram_id=88888, first_name='Free student')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(self.student))
        self.resource = Resource.objects.create(title='File', file='inbox/lecture notes.pdf', status='published', access_level='premium')

    def s3(self):
        return S3Storage(access_key='test-key', secret_key='test-secret', bucket_name='private-bucket',
                         endpoint_url='https://example.r2.cloudflarestorage.com', region_name='auto',
                         signature_version='s3v4', custom_domain='public.example.com', querystring_auth=False,
                         location='media')

    def test_r2_signs_get_without_opening_file_even_with_legacy_public_settings(self):
        storage = self.s3()
        self.resource.file.storage = storage
        request = type('Request', (), {'student': self.student})()
        with patch.object(storage, '_open', side_effect=AssertionError('Must not stream R2 bytes')):
            url = resource_file_url(self.resource, request)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, 'example.r2.cloudflarestorage.com')
        self.assertIn('/private-bucket/media/inbox/lecture%20notes.pdf', parsed.path)
        self.assertEqual(query['X-Amz-Expires'], ['900'])
        self.assertIn('X-Amz-Signature', query)
        self.assertEqual(query['response-content-type'], ['application/pdf'])
        self.assertIn('attachment', query['response-content-disposition'][0])
        preview = parse_qs(urlsplit(resource_file_url(self.resource, request, inline=True)).query)
        self.assertTrue(preview['response-content-disposition'][0].startswith('inline'))

    @override_settings(STORAGES={'default': {'BACKEND': 'storages.backends.s3.S3Storage', 'OPTIONS': {
        'access_key': 'test-key', 'secret_key': 'test-secret', 'bucket_name': 'private-bucket',
        'endpoint_url': 'https://example.r2.cloudflarestorage.com', 'region_name': 'auto', 'signature_version': 's3v4',
    }}})
    def test_api_returns_direct_r2_links_to_free_students_and_counts_issuance(self):
        with patch.object(S3Storage, '_open', side_effect=AssertionError('No file read')):
            response = self.client.post(f'/api/resources/{self.resource.pk}/download/')
            detail = self.client.get(f'/api/resources/{self.resource.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(urlsplit(response.data['url']).hostname, 'example.r2.cloudflarestorage.com')
        self.assertFalse(detail.data['is_locked'])
        self.assertEqual(detail.data['access_level'], 'free')
        self.assertIn('X-Amz-Signature', detail.data['file_url'])
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.downloads_count, 1)

    def test_local_preview_is_signed_inline_and_does_not_increment_download_count(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.resource.file.save('local.pdf', SimpleUploadedFile('local.pdf', b'%PDF-1.4 local file'))
            response = self.client.get(f'/api/resources/{self.resource.pk}/')
            path = urlsplit(response.data['file_url']).path
            self.client.credentials()
            preview = self.client.get(path)
            self.assertEqual(preview.status_code, 200)
            self.assertTrue(preview['Content-Disposition'].startswith('inline'))
            self.assertEqual(b''.join(preview.streaming_content), b'%PDF-1.4 local file')
            self.resource.refresh_from_db()
            self.assertEqual(self.resource.downloads_count, 0)
            with patch('django.core.signing.TimestampSigner.timestamp', return_value='0'):
                self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(self.student))
                expired_url = self.client.get(f'/api/resources/{self.resource.pk}/').data['file_url']
            self.client.credentials()
            self.assertEqual(self.client.get(urlsplit(expired_url).path).status_code, 403)

    @override_settings(STORAGES={'default': {'BACKEND': 'storages.backends.s3.S3Storage', 'OPTIONS': {
        'access_key': 'test-key', 'secret_key': 'test-secret', 'bucket_name': 'private-bucket',
        'endpoint_url': 'https://example.r2.cloudflarestorage.com', 'region_name': 'auto', 'signature_version': 's3v4',
    }}})
    def test_legacy_signed_r2_link_redirects_without_streaming(self):
        from django.core import signing
        from .delivery import DOWNLOAD_SALT
        token = signing.dumps({'resource_id': self.resource.pk, 'file_name': self.resource.file.name}, salt=DOWNLOAD_SALT)
        self.client.credentials()
        with patch.object(S3Storage, '_open', side_effect=AssertionError('No file read')):
            response = self.client.get(f'/api/resources/{self.resource.pk}/download/file/', {'token': token})
        self.assertEqual(response.status_code, 302)
        self.assertIn('X-Amz-Signature', response['Location'])
        self.assertEqual(urlsplit(response['Location']).hostname, 'example.r2.cloudflarestorage.com')

    def test_missing_file_does_not_increment_counter(self):
        self.resource.file = ''
        self.resource.save()
        response = self.client.post(f'/api/resources/{self.resource.pk}/download/')
        self.assertEqual(response.status_code, 404)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.downloads_count, 0)


class FileValidationAndRetentionTests(APITestCase):
    def test_size_extension_and_header_validation_preserve_file_position(self):
        valid = SimpleUploadedFile('valid.pdf', b'%PDF test')
        valid.seek(2)
        validate_exam_pdf(valid)
        self.assertEqual(valid.tell(), 2)
        for file in [SimpleUploadedFile('empty.pdf', b''), SimpleUploadedFile('script.html', b'<html>'),
                     SimpleUploadedFile('fake.pdf', b'<html>'), SimpleUploadedFile('bad.docx', b'not a zip')]:
            with self.assertRaises(ValidationError):
                validate_document_upload(file)
        with override_settings(MAX_EXAM_PDF_UPLOAD_BYTES=4):
            with self.assertRaises(ValidationError):
                validate_exam_pdf(valid)

    def test_orphan_audit_protects_all_three_file_reference_types(self):
        import os
        import time
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            root = Path(directory) / 'inbox'
            root.mkdir()
            for name in ('resource.pdf', 'inbox.pdf', 'exam.pdf', 'orphan.pdf', 'recent.pdf'):
                path = root / name
                path.write_bytes(b'%PDF')
                if name != 'recent.pdf':
                    os.utime(path, (time.time() - 60 * 86400,) * 2)
            Resource.objects.create(title='Resource', file='inbox/resource.pdf')
            FileInbox.objects.create(telegram_message_id=2, file='inbox/inbox.pdf', original_filename='inbox.pdf', posted_date=timezone.now())
            ExamPDFUpload.objects.create(file='inbox/exam.pdf', original_name='exam.pdf', pdf_type='schedule')
            out = StringIO()
            call_command('audit_orphan_files', prefix='inbox', stdout=out)
            self.assertIn('Review orphan candidate: inbox/orphan.pdf', out.getvalue())
            for name in ('resource.pdf', 'inbox.pdf', 'exam.pdf', 'recent.pdf'):
                self.assertNotIn('Review orphan candidate: inbox/' + name, out.getvalue())
            self.assertEqual(len(list(root.iterdir())), 5)

    def test_compaction_preserves_update_identity_and_failed_work(self):
        from datetime import timedelta
        completed = TelegramUpdate.objects.create(update_id=123, payload={'message': 'large body'}, status='processed')
        failed = TelegramUpdate.objects.create(update_id=124, payload={'message': 'retry input'}, status='failed')
        TelegramUpdate.objects.update(created_at=timezone.now() - timedelta(days=100))
        call_command('compact_completed_work', stdout=StringIO())
        completed.refresh_from_db()
        self.assertTrue(completed.payload)
        call_command('compact_completed_work', apply=True, stdout=StringIO())
        completed.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(completed.payload, {})
        self.assertEqual(completed.update_id, 123)
        self.assertTrue(failed.payload)


class AttendanceOCRContractTests(APITestCase):
    def test_fallback_uses_structured_text_and_rejects_partial_imports(self):
        from apps.bot.processor import ExtractionResult
        from apps.exams.parsers.attendance_parser import _extract_pdf_text
        with patch('pdfplumber.open', side_effect=RuntimeError('Digital read unavailable')):
            with patch('apps.bot.processor.extract_pdf_with_ocr', return_value=ExtractionResult('OCR text')):
                self.assertEqual(_extract_pdf_text('scanned.pdf'), 'OCR text')
            with patch('apps.bot.processor.extract_pdf_with_ocr', return_value=ExtractionResult('Partial', 'partial', 'One page failed')):
                with self.assertRaises(ValueError):
                    _extract_pdf_text('scanned.pdf')
