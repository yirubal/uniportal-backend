from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.content.models import Course, Department, FileInbox, Resource
from apps.quiz.models import Chapter, ExamPaper, Question
from .ai_tasks import queue_question_extraction
from .extractor import GeminiQuotaExceeded, _extract_from_chunk
from .models import QuestionExtraction
from .test_worker import QUESTION
from .worker import claim_work, process_claimed_work


class AIPaperExtractionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('paper-ai-admin')
        self.client.force_login(self.user)
        self.course = Course.objects.create(name='Management', code='MAN101')
        self.chapter = Chapter.objects.create(course=self.course, number=1, title='Leadership')
        self.paper = ExamPaper.objects.create(title='Practice paper', course=self.course,
                                             exam_type='quiz', year=2026)
        self.inbox = FileInbox.objects.create(telegram_message_id=5001, original_filename='practice.pdf',
            posted_date=timezone.now(), processing_status='processed', extracted_text='source question ' * 10)
        self.url = reverse('admin:quiz_exampaper_extract_questions', args=[self.paper.pk])

    def queue(self, **changes):
        return queue_question_extraction(**{
            'inbox': self.inbox, 'exam_paper': self.paper,
            'chapter': self.chapter, 'requested_by': self.user, **changes})[0]

    def process(self, rows=None):
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=rows or [QUESTION]) as provider:
            process_claimed_work('ai', *claim_work('ai'))
        return provider

    def test_admin_queues_once_then_worker_assigns_inactive_drafts_with_source(self):
        self.assertContains(self.client.get(reverse('admin:quiz_exampaper_change', args=[self.paper.pk])), 'Extract questions with AI')
        payload = {'exam_paper': self.paper.pk, 'chapter': self.chapter.pk, 'inbox': self.inbox.pk}
        with patch('apps.bot.ai_tasks._extract_from_chunk') as provider:
            for _ in range(2):
                self.assertEqual(self.client.post(self.url, payload).status_code, 302)
            provider.assert_not_called()
        self.assertEqual(QuestionExtraction.objects.count(), 1)
        self.assertFalse(Question.objects.exists())
        self.process()
        job = QuestionExtraction.objects.get()
        question = Question.objects.get()
        self.assertEqual((question.exam_paper_id, question.chapter_id, question.source_extraction_id),
                         (self.paper.pk, self.chapter.pk, job.pk))
        self.assertEqual(question.topic_tags, ['Chapter 1: Leadership'])
        self.assertFalse(question.is_active)
        self.assertEqual(job.requested_by_id, self.user.pk)
        self.assertEqual(job.source_text, self.inbox.extracted_text.strip())
        self.assertEqual(job.provider_calls, 1)
        self.assertContains(self.client.get(self.url), 'Review 1 question')
        self.assertEqual(self.client.get(reverse('admin:quiz_question_changelist'),
            {'source_extraction__id__exact': job.pk}).context['cl'].result_count, 1)
        self.assertContains(self.client.get(reverse('admin:quiz_question_change', args=[question.pk])), 'AI source')
        self.assertContains(self.client.get(reverse('admin:bot_questionextraction_change', args=[job.pk])), self.inbox.extracted_text.strip())

    def test_resource_source_reuses_completed_content_without_another_provider_call(self):
        self.queue()
        self.process()
        resource = Resource.objects.create(title='Same exam', extracted_text=self.inbox.extracted_text)
        job = self.queue(inbox=None, resource=resource)
        self.process().assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.provider_calls, 0)
        self.assertEqual(job.status, 'processed')
        self.assertEqual(job.draft_questions.count(), 1)

    def test_exit_paper_needs_department_but_no_course_or_chapter(self):
        department = Department.objects.create(name='Management department')
        paper = ExamPaper.objects.create(title='Exit Model', exam_type='exit_model', department=department, year=2026)
        self.queue(exam_paper=paper, chapter=None)
        self.process()
        question = Question.objects.get()
        self.assertEqual(question.exam_paper_id, paper.pk)
        self.assertIsNone(question.chapter_id)
        self.assertIsNone(paper.course_id)

    def test_invalid_source_and_chapter_are_rejected_before_queueing(self):
        resource = Resource.objects.create(title='Notes', extracted_text='text ' * 20)
        other = Course.objects.create(name='Other course', code='OTHER')
        chapter = Chapter.objects.create(course=other, number=1, title='Other chapter')
        for changes in ({'resource': resource}, {'chapter': chapter}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.queue(**changes)
        self.assertFalse(QuestionExtraction.objects.exists())
        self.assertEqual(self.client.post(self.url, {'exam_paper': self.paper.pk,
            'inbox': self.inbox.pk, 'chapter': chapter.pk}).status_code, 200)
        self.assertFalse(QuestionExtraction.objects.exists())

    def test_reposting_a_different_target_does_not_move_previous_work(self):
        job = self.queue()
        other = ExamPaper.objects.create(title='Other paper', course=self.course, exam_type='quiz', year=2026)
        with self.assertRaisesMessage(ValueError, 'already has extraction'):
            self.queue(exam_paper=other)
        job.refresh_from_db()
        self.assertEqual(job.exam_paper_id, self.paper.pk)
        response = self.client.post(self.url, {'exam_paper': other.pk, 'chapter': self.chapter.pk, 'inbox': self.inbox.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(QuestionExtraction.objects.count(), 1)

    def test_permissions_prevent_unapproved_source_reads_and_queueing(self):
        user = get_user_model().objects.create_user('limited-ai-admin', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        user.user_permissions.add(*Permission.objects.filter(codename__in=['change_exampaper', 'add_question', 'view_chapter']))
        response = self.client.post(self.url, {'exam_paper': self.paper.pk, 'chapter': self.chapter.pk, 'inbox': self.inbox.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionExtraction.objects.exists())

    def test_inbox_action_opens_target_selection_without_queueing(self):
        response = self.client.post(reverse('admin:content_fileinbox_changelist'), {
            'action': 'extract_questions', '_selected_action': [self.inbox.pk], 'index': 0})
        self.assertRedirects(response, reverse('admin:quiz_exampaper_extract_questions_select') + f'?inbox={self.inbox.pk}')
        self.assertFalse(QuestionExtraction.objects.exists())

    def test_source_snapshot_survives_resource_edit_and_deletion(self):
        resource = Resource.objects.create(title='Exam source', extracted_text='saved source ' * 10)
        job = self.queue(inbox=None, resource=resource)
        Resource.objects.filter(pk=resource.pk).update(extracted_text='changed source')
        resource.delete()
        self.process()
        job.refresh_from_db()
        self.assertIsNone(job.resource_id)
        self.assertEqual(job.source_text, ('saved source ' * 10).strip())
        self.assertEqual(job.source_label, 'Exam source')
        self.assertEqual(job.draft_questions.count(), 1)

    def test_deleted_target_fails_without_provider_requests(self):
        job = self.queue()
        self.paper.delete()
        self.process().assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertFalse(Question.objects.exists())

    def test_target_is_rechecked_before_saving_and_retry_reuses_completed_chunk(self):
        job = self.queue()
        def pause_paper(*args):
            ExamPaper.objects.filter(pk=self.paper.pk).update(is_active=False)
            return [QUESTION]
        with patch('apps.bot.ai_tasks._extract_from_chunk', side_effect=pause_paper):
            process_claimed_work('ai', *claim_work('ai'))
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertFalse(Question.objects.exists())
        ExamPaper.objects.filter(pk=self.paper.pk).update(is_active=True)
        QuestionExtraction.objects.filter(pk=job.pk).update(status='pending', next_attempt_at=timezone.now())
        self.process().assert_not_called()
        self.assertEqual(job.draft_questions.count(), 1)

    def test_changed_model_version_stops_before_a_provider_request(self):
        job = self.queue()
        QuestionExtraction.objects.filter(pk=job.pk).update(version='previous-prompt:old-model')
        self.process().assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.provider_calls, 0)

    @override_settings(AI_MAX_CALLS_PER_JOB=1)
    def test_call_budget_stops_before_repaying_completed_chunks(self):
        self.inbox.extracted_text = 'x' * 8100
        self.inbox.save(update_fields=['extracted_text'])
        job = self.queue()
        self.process().assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.provider_calls, 1)
        self.assertIn('0', job.chunks)
        self.assertFalse(Question.objects.exists())

    def test_quota_cooldown_covers_existing_and_new_jobs(self):
        job = self.queue()
        resource = Resource.objects.create(title='Another source', extracted_text='other source ' * 10)
        second = self.queue(inbox=None, resource=resource)
        before = timezone.now()
        with patch('apps.bot.ai_tasks._extract_from_chunk', side_effect=GeminiQuotaExceeded('quota')):
            process_claimed_work('ai', *claim_work('ai'))
        for row in (job, second):
            row.refresh_from_db()
            self.assertEqual(row.status, 'pending')
            self.assertGreaterEqual(row.next_attempt_at, before + timedelta(seconds=1700))
        third = Resource.objects.create(title='New during cooldown', extracted_text='third source ' * 10)
        newly_queued = self.queue(inbox=None, resource=third)
        self.assertGreaterEqual(newly_queued.next_attempt_at, job.next_attempt_at)
        self.assertIsNone(claim_work('ai'))

    def test_sdk_quota_errors_are_sanitized_and_permanent_errors_do_not_loop(self):
        from google.genai.errors import ClientError
        client = Mock()
        for code, expected in ((429, GeminiQuotaExceeded), (403, ValueError)):
            client.models.generate_content.side_effect = ClientError(code, {'error': {'message': 'private-provider-detail'}})
            with self.subTest(code=code), patch('google.genai.Client', return_value=client):
                with self.assertRaises(expected) as error:
                    _extract_from_chunk('test-key', 'source text')
                self.assertNotIn('private-provider-detail', str(error.exception))
