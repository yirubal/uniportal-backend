from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Student, SubscriptionPlan, SubscriptionRequest
from apps.accounts.notifications import queue_broadcast
from apps.accounts.services import approve_subscription_request
from apps.content.models import FileInbox
from apps.exams.models import ExamPDFUpload, ExamTerm
from apps.quiz.models import Question
from .ai_tasks import queue_question_extraction
from .downloader import download_file, safe_filename
from .models import NotificationDelivery, QuestionExtraction, TelegramUpdate
from .processor import extract_pdf_with_ocr
from .worker import claim_work, fail_work, process_claimed_work, recover_stale_claims


QUESTION = {'question_type': 'mcq', 'question': 'What is correct?', 'option_a': 'Yes', 'option_b': 'No',
            'option_c': '', 'option_d': '', 'option_e': '', 'option_f': '', 'correct_option': 'a', 'explanation': ''}


class WorkerLifecycleTests(TestCase):
    def setUp(self):
        self.update = TelegramUpdate.objects.create(update_id=10, payload={'update_id': 10})

    def test_claim_is_once_only_and_wrong_token_cannot_complete(self):
        claim = claim_work('update')
        self.assertIsNone(claim_work('update'))
        with patch('apps.bot.application.process_telegram_update', new_callable=AsyncMock) as process:
            process_claimed_work('update', self.update.pk, uuid4())
            process.assert_not_awaited()
            process_claimed_work('update', *claim)
            process.assert_awaited_once_with({'update_id': 10})
        self.update.refresh_from_db()
        self.assertEqual(self.update.status, 'processed')
        self.assertEqual(self.update.attempt_count, 1)
        self.assertIsNone(self.update.claim_token)

    def test_transient_failure_backoff_and_attempt_limit(self):
        for attempt in range(1, 6):
            TelegramUpdate.objects.filter(pk=self.update.pk).update(next_attempt_at=timezone.now())
            claim = claim_work('update')
            fail_work('update', *claim, 'Temporary failure')
            self.update.refresh_from_db()
            self.assertEqual(self.update.attempt_count, attempt)
            self.assertGreater(self.update.next_attempt_at, timezone.now())
            self.assertEqual(self.update.status, 'failed' if attempt == 5 else 'pending')
            self.assertIsNone(claim_work('update'))
        recover_stale_claims()
        self.update.refresh_from_db()
        self.assertEqual(self.update.status, 'failed')

    def test_only_stale_claims_recover_and_old_token_cannot_finish(self):
        original = claim_work('update')
        self.assertEqual(recover_stale_claims(), 0)
        TelegramUpdate.objects.filter(pk=self.update.pk).update(claimed_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(recover_stale_claims(), 1)
        TelegramUpdate.objects.filter(pk=self.update.pk).update(next_attempt_at=timezone.now())
        replacement = claim_work('update')
        self.assertNotEqual(original[1], replacement[1])
        with patch('apps.bot.application.process_telegram_update', new_callable=AsyncMock) as process:
            process_claimed_work('update', *original)
            process.assert_not_awaited()
        self.update.refresh_from_db()
        self.assertEqual(self.update.claim_token, replacement[1])

    def test_telegram_retry_after_is_respected_by_update_handler(self):
        from telegram.error import RetryAfter
        with patch('apps.bot.application.process_telegram_update', new_callable=AsyncMock, side_effect=RetryAfter(120)):
            process_claimed_work('update', *claim_work('update'))
        self.update.refresh_from_db()
        self.assertEqual(self.update.status, 'pending')
        self.assertGreater(self.update.next_attempt_at, timezone.now() + timedelta(seconds=115))

    def test_handler_failure_remains_retryable_instead_of_being_acknowledged_as_processed(self):
        with patch('apps.bot.application.process_telegram_update', new_callable=AsyncMock, side_effect=RuntimeError('Failed')):
            process_claimed_work('update', *claim_work('update'))
        self.update.refresh_from_db()
        self.assertEqual(self.update.status, 'pending')
        self.assertIn('RuntimeError', self.update.error_message)

    def test_inbox_partial_and_empty_results_are_distinct(self):
        item = FileInbox.objects.create(telegram_message_id=30, original_filename='partial.pdf', posted_date=timezone.now())
        with patch('apps.bot.tasks.process_inbox_item', return_value={'extracted_text': 'Partial text', 'processing_error': '1 skipped page', 'extraction_outcome': 'partial'}):
            process_claimed_work('inbox', *claim_work('inbox'))
        item.refresh_from_db()
        self.assertEqual(item.processing_status, 'processed')
        self.assertEqual(item.extraction_outcome, 'partial')
        self.assertIn('skipped', item.processing_error)
        empty = FileInbox.objects.create(telegram_message_id=31, original_filename='empty.pdf', posted_date=timezone.now())
        process_claimed_work('inbox', *claim_work('inbox'))
        empty.refresh_from_db()
        self.assertEqual(empty.processing_status, 'failed')
        self.assertIn('no file', empty.processing_error)

    def test_failed_exam_import_rolls_back_partial_rows(self):
        upload = ExamPDFUpload.objects.create(original_name='broken.pdf', pdf_type='schedule')
        def partial_import(row):
            ExamTerm.objects.create(year=9999, term=1)
            row.status = 'failed'
            row.save()
            return False, 0, 'Invalid PDF'
        with patch('apps.exams.services.process_schedule_pdf', side_effect=partial_import):
            process_claimed_work('exam', *claim_work('exam'))
        self.assertFalse(ExamTerm.objects.filter(year=9999).exists())
        upload.refresh_from_db()
        self.assertEqual(upload.status, 'failed')


class DurableNotificationTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(telegram_id=70001, first_name='Recipient')
        self.plan = SubscriptionPlan.objects.create(plan_id='month', name='Month', price=100, days=30)
        self.payment = SubscriptionRequest.objects.create(student=self.student, plan=self.plan, amount=100, reference='UNI-WORK01')
        self.actor = get_user_model().objects.create_user(username='worker-admin')

    def test_payment_and_delivery_intent_commit_or_rollback_together(self):
        with patch('httpx.post') as network:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    approve_subscription_request(self.payment.pk, self.actor)
                    self.assertEqual(NotificationDelivery.objects.count(), 1)
                    raise RuntimeError('Abort surrounding transaction')
            self.assertFalse(NotificationDelivery.objects.exists())
            self.payment.refresh_from_db()
            self.student.refresh_from_db()
            self.assertEqual(self.payment.status, 'pending')
            self.assertIsNone(self.student.subscription_expiry)
            approve_subscription_request(self.payment.pk, self.actor)
            approve_subscription_request(self.payment.pk, self.actor)
            self.assertEqual(NotificationDelivery.objects.count(), 1)
            network.assert_not_called()

    def test_broadcast_retries_only_failed_recipient_and_retains_progress(self):
        Student.objects.create(telegram_id=70002, first_name='Second')
        Student.objects.create(telegram_id=70003, first_name='Inactive', is_active=False)
        with patch('httpx.post') as network:
            broadcast = queue_broadcast('Hello', sent_by=self.actor)
            network.assert_not_called()
        self.assertEqual(broadcast.total_users, 2)
        first = claim_work('notification')
        with patch('apps.bot.worker.deliver_notification'):
            process_claimed_work('notification', *first)
        second = claim_work('notification')
        with patch('apps.bot.worker.deliver_notification', side_effect=RuntimeError('Temporary')):
            process_claimed_work('notification', *second)
        broadcast.refresh_from_db()
        self.assertEqual((broadcast.success_count, broadcast.failed_count), (1, 0))
        NotificationDelivery.objects.filter(pk=second[0]).update(next_attempt_at=timezone.now())
        retry = claim_work('notification')
        self.assertEqual(retry[0], second[0])
        with patch('apps.bot.worker.deliver_notification') as send:
            process_claimed_work('notification', *retry)
            send.assert_called_once()
        broadcast.refresh_from_db()
        self.assertEqual((broadcast.success_count, broadcast.failed_count), (2, 0))
        self.assertIsNone(claim_work('notification'))

    @override_settings(TELEGRAM_BOT_TOKEN='test')
    def test_rate_limit_reschedules_delivery_and_other_pending_messages(self):
        broadcast = queue_broadcast('Hello')
        NotificationDelivery.objects.create(chat_id=1, text='Other', deduplication_key='other')
        response = Mock(status_code=429)
        response.json.return_value = {'ok': False, 'parameters': {'retry_after': 120}}
        with patch('httpx.post', return_value=response):
            process_claimed_work('notification', *claim_work('notification'))
        self.assertIsNone(claim_work('notification'))
        self.assertEqual(NotificationDelivery.objects.filter(status='pending').count(), 2)
        self.assertEqual(NotificationDelivery.objects.get(broadcast=broadcast).attempt_count, 1)

    @override_settings(TELEGRAM_BOT_TOKEN='test')
    def test_invalid_recipient_is_terminal_and_updates_broadcast_counts(self):
        broadcast = queue_broadcast('Hello')
        response = Mock(status_code=403)
        response.json.return_value = {'ok': False, 'error_code': 403}
        with patch('httpx.post', return_value=response):
            process_claimed_work('notification', *claim_work('notification'))
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.failed_count, 1)
        self.assertIsNone(claim_work('notification'))

    def test_invalid_broadcast_has_no_partial_log_or_deliveries(self):
        with self.assertRaises(ValueError):
            queue_broadcast('a' * 4097)
        self.assertFalse(NotificationDelivery.objects.exists())


class AIExtractionTests(TestCase):
    def inbox(self, message_id, text):
        return FileInbox.objects.create(telegram_message_id=message_id, original_filename='questions.pdf', posted_date=timezone.now(),
                                       extracted_text=text, processing_status='processed')

    def test_sixth_choice_survives_worker_extraction_and_draft_creation(self):
        queue_question_extraction(self.inbox(44, 'a' * 100))
        row = {**QUESTION, 'option_f': 'Sixth choice', 'correct_option': 'f'}
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=[row]):
            process_claimed_work('ai', *claim_work('ai'))
        question = Question.objects.get()
        self.assertEqual((question.option_f, question.correct_option), ('Sixth choice', 'f'))
        self.assertFalse(question.is_active)

    def test_completed_chunks_survive_retry_and_draft_creation_is_once_only(self):
        extraction, _ = queue_question_extraction(self.inbox(40, 'a' * 8100))
        with patch('apps.bot.ai_tasks._extract_from_chunk', side_effect=[[QUESTION], RuntimeError('Provider timeout')]) as generate:
            process_claimed_work('ai', *claim_work('ai'))
            self.assertEqual(generate.call_count, 2)
        extraction.refresh_from_db()
        self.assertEqual(len(extraction.chunks), 1)
        self.assertFalse(Question.objects.exists())
        QuestionExtraction.objects.filter(pk=extraction.pk).update(next_attempt_at=timezone.now())
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=[QUESTION]) as generate:
            process_claimed_work('ai', *claim_work('ai'))
            generate.assert_called_once()
        self.assertEqual(Question.objects.count(), 2)
        self.assertFalse(Question.objects.filter(is_active=True).exists())
        self.assertIsNone(claim_work('ai'))
        _, created = queue_question_extraction(extraction.inbox)
        self.assertFalse(created)

    def test_identical_completed_source_reuses_cache_without_paid_call(self):
        original, _ = queue_question_extraction(self.inbox(41, 'a' * 100))
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=[QUESTION]):
            process_claimed_work('ai', *claim_work('ai'))
        duplicate, _ = queue_question_extraction(self.inbox(42, 'a' * 100))
        with patch('apps.bot.ai_tasks._extract_from_chunk') as generate:
            process_claimed_work('ai', *claim_work('ai'))
            generate.assert_not_called()
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.status, 'processed')
        self.assertEqual(Question.objects.count(), 2)

    @override_settings(GEMINI_MODEL='configured-model')
    def test_pinned_sdk_call_has_timeout_and_validates_json_response(self):
        import json
        from .extractor import _extract_from_chunk
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text=json.dumps([QUESTION]))
        with patch('google.genai.Client', return_value=client) as factory:
            result = _extract_from_chunk('test-key', 'a' * 100)
        self.assertEqual(result, [QUESTION])
        self.assertEqual(factory.call_args.kwargs['http_options'].timeout, 60000)
        self.assertEqual(client.models.generate_content.call_args.kwargs['model'], 'configured-model')
        client.models.generate_content.return_value = SimpleNamespace(text='[{"question":')
        with patch('google.genai.Client', return_value=client):
            with self.assertRaises(ValueError):
                _extract_from_chunk('test-key', 'a' * 100)

    def test_invalid_output_fails_before_creating_any_questions(self):
        extraction, _ = queue_question_extraction(self.inbox(43, 'a' * 100))
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=[QUESTION, {'question_type': 'bogus'}]):
            process_claimed_work('ai', *claim_work('ai'))
        extraction.refresh_from_db()
        self.assertEqual(extraction.status, 'failed')
        self.assertFalse(Question.objects.exists())


class FileProcessingTests(TestCase):
    def test_download_uses_unique_safe_paths_and_removes_failed_download(self):
        file = SimpleNamespace(download_to_drive=AsyncMock())
        bot = SimpleNamespace(get_file=AsyncMock(return_value=file))
        first = async_to_sync(download_file)(bot, 'file', '../../same.pdf')
        second = async_to_sync(download_file)(bot, 'file', '../../same.pdf')
        try:
            self.assertNotEqual(first, second)
            self.assertEqual(safe_filename('..\\..\\same.pdf'), 'same.pdf')
            self.assertEqual(Path(first).suffix, '.pdf')
        finally:
            Path(first).unlink(missing_ok=True)
            Path(second).unlink(missing_ok=True)
        async def fail(path):
            Path(path).write_bytes(b'partial download')
            raise RuntimeError('Network failed')
        file.download_to_drive.side_effect = fail
        with self.assertRaises(RuntimeError):
            async_to_sync(download_file)(bot, 'file', 'same.pdf')
        failed_path = file.download_to_drive.call_args.args[0]
        self.assertFalse(Path(failed_path).exists())

    def test_digital_pdf_extracts_text_with_pinned_pdfplumber_without_ocr(self):
        from .processor import extract_pdf
        text = 'This is a digital university document with enough text to avoid OCR processing.'
        stream = f'BT /F1 12 Tf 30 100 Td ({text}) Tj ET'.encode()
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
                   b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
                   b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
        data = b'%PDF-1.4\n'
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(data))
            data += f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n'
        xref = len(data)
        data += b'xref\n0 6\n0000000000 65535 f \n'
        data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
        data += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'digital.pdf'
            path.write_bytes(data)
            with patch('apps.bot.processor.extract_pdf_with_ocr') as ocr:
                result = extract_pdf(str(path))
            self.assertEqual(result.text, text)
            ocr.assert_not_called()

    def test_mixed_digital_and_scanned_pdf_is_reported_as_partial(self):
        from .processor import extract_pdf
        digital = Mock(images=[])
        digital.extract_text.return_value = 'University lecture notes with enough text for the digital extraction path.'
        scanned = Mock(images=[{'image': True}])
        scanned.extract_text.return_value = ''
        context = Mock()
        context.__enter__ = Mock(return_value=SimpleNamespace(pages=[digital, scanned]))
        context.__exit__ = Mock(return_value=False)
        with patch('pdfplumber.open', return_value=context):
            result = extract_pdf('mixed.pdf')
        self.assertEqual(result.outcome, 'partial')
        self.assertIn('1 image-only page', result.note)

    def test_unknown_page_count_never_renders_all_pages(self):
        with patch('pdf2image.pdfinfo_from_path', side_effect=RuntimeError('No page count')):
            with patch('pdf2image.convert_from_path') as render:
                with self.assertRaises(RuntimeError):
                    extract_pdf_with_ocr('unknown.pdf')
                render.assert_not_called()

    def test_partial_ocr_uses_library_timeouts_and_closes_images(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.pdf'
            path.write_bytes(b'PDF')
            images = [Mock(), Mock()]
            with patch('pdf2image.pdfinfo_from_path', return_value={'Pages': 2}):
                with patch('pdf2image.convert_from_path', side_effect=[[images[0]], [images[1]]]) as render:
                    with patch('pytesseract.image_to_string', side_effect=['Some text', RuntimeError('timeout')]) as ocr:
                        result = extract_pdf_with_ocr(str(path))
            self.assertEqual((result.text, result.outcome), ('Some text', 'partial'))
            self.assertEqual(render.call_args.kwargs['first_page'], 2)
            self.assertIn('timeout', render.call_args.kwargs)
            self.assertIn('timeout', ocr.call_args.kwargs)
            for image in images:
                image.close.assert_called_once()
