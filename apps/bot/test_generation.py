from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.content.models import Course, Department, Resource
from apps.quiz.forms import PracticePaperGenerationForm
from apps.quiz.models import Chapter, ExamPaper, Question
from .ai_tasks import queue_question_extraction
from .extractor import GeminiQuotaExceeded
from .generation import _validate_generated_questions, queue_paper_generation
from .models import QuestionExtraction
from .worker import claim_work, process_claimed_work

SOURCE = 'Leadership involves guiding people toward shared goals. Planning establishes objectives and actions. '


def rows(count=1, start=0):
    return [dict(question_type='mcq', question=f'Which description explains leadership? Version {i}',
        option_a='Guiding people', option_b='Ignoring goals', option_c='Avoiding plans', option_d='Working alone',
        option_e='', option_f='', correct_option='a', explanation='Leadership guides people toward shared goals.',
        source_quote='Leadership involves guiding people toward shared goals.') for i in range(start, start + count)]


class PracticePaperGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('generation-admin')
        self.client.force_login(self.user)
        self.course = Course.objects.create(name='Management', code='MAN')
        self.chapter = Chapter.objects.create(course=self.course, number=1, title='Leadership')
        self.resource = Resource.objects.create(title='Leadership notes', extracted_text=SOURCE)
        self.url = reverse('admin:quiz_exampaper_generate_paper')
        self.paper_values = dict(title='Practice variation', course=self.course, exam_type='quiz', year=2026,
                                 duration_minutes=30, access_level='free')
        self.options = dict(count=1, question_type='mcq', difficulty='hard', focus='Leadership')

    def queue(self, **changes):
        return queue_paper_generation(**{'resource': self.resource, 'chapter': self.chapter, 'requested_by': self.user,
            'submission_token': uuid4(), 'paper_values': self.paper_values, 'generation_settings': self.options, **changes})[0]

    def payload(self):
        form = self.client.get(self.url).context['form']
        return dict(title='New quiz', course=self.course.pk, exam_type='quiz', year=2026, duration_minutes=30,
                    access_level='free', resource=self.resource.pk, chapter=self.chapter.pk, **self.options,
                    submission_token=form.initial['submission_token'])

    def process(self, **mock_options):
        with patch('apps.bot.generation._request_question_json', **(mock_options or {'return_value': rows()})) as provider:
            process_claimed_work('ai', *claim_work('ai'))
        return provider

    def test_admin_creates_inactive_paper_once_per_submission_without_web_provider_calls(self):
        response = self.client.get(reverse('admin:quiz_exampaper_changelist'))
        self.assertContains(response, 'Generate practice paper')
        payload = self.payload()
        with patch('apps.bot.generation._request_question_json') as provider:
            for _ in range(2):
                self.assertEqual(self.client.post(self.url, payload).status_code, 302)
            provider.assert_not_called()
        self.assertEqual(ExamPaper.objects.count(), 1)
        self.assertEqual(QuestionExtraction.objects.count(), 1)
        self.assertFalse(ExamPaper.objects.get().is_active)
        self.assertFalse(Question.objects.exists())
        self.process().assert_called_once()
        question = Question.objects.get()
        job = QuestionExtraction.objects.get()
        self.assertEqual(job.status, 'processed')
        self.assertEqual(question.exam_paper_id, job.exam_paper_id)
        self.assertEqual(question.chapter_id, self.chapter.pk)
        self.assertEqual(question.source_quote, rows()[0]['source_quote'])
        self.assertEqual(question.difficulty, 'hard')
        self.assertFalse(question.is_active)
        self.assertFalse(job.exam_paper.is_active)
        self.assertContains(self.client.get(self.url), 'Review 1 question')

    def test_new_submission_allows_variation_and_extraction_for_the_same_source(self):
        self.queue()
        second = self.queue()
        self.assertEqual(ExamPaper.objects.count(), 2)
        second.exam_paper.is_active = True
        second.exam_paper.save(update_fields=['is_active'])
        extracted, created = queue_question_extraction(resource=self.resource, exam_paper=second.exam_paper)
        self.assertTrue(created)
        self.assertEqual(QuestionExtraction.objects.filter(resource=self.resource).count(), 3)
        self.assertEqual(queue_question_extraction(resource=self.resource, exam_paper=second.exam_paper), (extracted, False))

    def test_exit_model_has_department_and_no_course(self):
        department = Department.objects.create(name='Management')
        values = {**self.paper_values, 'exam_type': 'exit_model', 'course': None, 'department': department}
        job = self.queue(paper_values=values, chapter=None)
        self.process()
        self.assertIsNone(job.exam_paper.course_id)
        self.assertEqual(Question.objects.get().exam_paper.department_id, department.pk)

    def test_invalid_parameters_do_not_leave_orphan_papers(self):
        for changes in ({'generation_settings': {**self.options, 'count': 31}},
                        {'submission_token': None},
                        {'paper_values': {**self.paper_values, 'exam_type': 'final'}},
                        {'paper_values': {**self.paper_values, 'exam_type': 'exit_model', 'course': None}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.queue(**changes)
        self.assertFalse(ExamPaper.objects.exists())
        self.assertFalse(QuestionExtraction.objects.exists())

    def test_permission_and_signed_token_checks(self):
        payload = self.payload()
        limited = get_user_model().objects.create_user('limited-generator', is_staff=True)
        self.client.force_login(limited)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        limited.user_permissions.add(*Permission.objects.filter(codename__in=[
            'add_exampaper', 'change_exampaper', 'add_question', 'view_course', 'view_chapter']))
        # A form token belongs to its admin; source choices also require permissions.
        self.assertEqual(self.client.post(self.url, payload).status_code, 200)
        limited.user_permissions.add(Permission.objects.get(codename='view_resource'))
        form = PracticePaperGenerationForm(payload, user=limited)
        self.assertFalse(form.is_valid())
        self.assertIn('submission_token', form.errors)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, {**payload, 'submission_token': 'tampered'}).status_code, 200)
        self.assertFalse(QuestionExtraction.objects.exists())

    def test_unverified_output_never_saves_questions(self):
        for field, value in [('source_quote', 'Invented citation that does not occur in the source.'),
                             ('correct_option', ''), ('explanation', ''), ('option_d', '')]:
            with self.subTest(field=field):
                output = rows()
                output[0][field] = value
                with self.assertRaises(ValueError):
                    _validate_generated_questions(output, SOURCE, 1, self.options)
        job = self.queue()
        invalid = rows()
        invalid[0]['source_quote'] = 'An invented quotation that is not in the source.'
        self.process(return_value=invalid)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertFalse(Question.objects.exists())

    def test_count_duplicates_and_wrong_types_are_rejected(self):
        for output, count in [(rows(), 2), (rows() * 2, 2), ([], 1)]:
            with self.subTest(output=output), self.assertRaises(ValueError):
                _validate_generated_questions(output, SOURCE, count, self.options)
        with self.assertRaises(ValueError):
            _validate_generated_questions(rows(), SOURCE, 1, {**self.options, 'question_type': 'essay'})

    def test_each_supported_question_type_has_reviewable_answer_shape(self):
        for kind in ('mcq', 'true_false', 'fill_blank', 'essay', 'matching'):
            output = deepcopy(rows())
            row = output[0]
            row['question_type'] = kind
            if kind != 'mcq':
                row.update({f'option_{letter}': '' for letter in 'abcdef'})
            if kind == 'true_false':
                row.update(option_a='True', option_b='False')
            if kind == 'fill_blank':
                row['correct_option'] = 'Leadership'
            if kind in ('essay', 'matching'):
                row['correct_option'] = ''
            if kind == 'matching':
                row.update(option_a='Leadership → Guiding people', option_b='Planning → Establishing objectives')
            with self.subTest(kind=kind):
                validated = _validate_generated_questions(output, SOURCE, 1, {**self.options, 'question_type': kind})
                self.assertEqual(validated[0]['difficulty'], 'hard')

    def test_retry_reuses_completed_batch_and_only_saves_complete_paper(self):
        job = self.queue(generation_settings={**self.options, 'count': 12})
        self.process(side_effect=[rows(10), RuntimeError('temporary outage')])
        job.refresh_from_db()
        self.assertIn('0', job.chunks)
        self.assertFalse(Question.objects.exists())
        QuestionExtraction.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        provider = self.process(return_value=rows(2, start=10))
        provider.assert_called_once()
        self.assertIn('Version 9', provider.call_args.args[1])
        job.refresh_from_db()
        self.assertEqual(job.provider_calls, 3)
        self.assertEqual(job.status, 'processed')
        self.assertEqual(job.draft_questions.count(), 12)

    def test_premature_publication_or_official_type_stops_before_provider_call(self):
        for changes in ({'is_active': True}, {'exam_type': 'final'}):
            job = self.queue()
            ExamPaper.objects.filter(pk=job.exam_paper_id).update(**changes)
            self.process().assert_not_called()
        self.assertFalse(Question.objects.exists())

    def test_publication_during_provider_call_is_rechecked_and_retry_reuses_output(self):
        job = self.queue()
        def activate_paper(*args):
            ExamPaper.objects.filter(pk=job.exam_paper_id).update(is_active=True)
            return rows()
        self.process(side_effect=activate_paper)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertFalse(Question.objects.exists())
        ExamPaper.objects.filter(pk=job.exam_paper_id).update(is_active=False)
        QuestionExtraction.objects.filter(pk=job.pk).update(status='pending', next_attempt_at=timezone.now())
        self.process().assert_not_called()
        self.assertEqual(job.draft_questions.count(), 1)

    def test_generation_results_do_not_replace_extraction_or_new_variation_calls(self):
        self.queue()
        self.process()
        paper = ExamPaper.objects.create(title='Existing source paper', course=self.course, exam_type='quiz', year=2026)
        queue_question_extraction(resource=self.resource, exam_paper=paper)
        with patch('apps.bot.ai_tasks._extract_from_chunk', return_value=rows()) as provider:
            process_claimed_work('ai', *claim_work('ai'))
            provider.assert_called_once()
        self.queue()
        self.process().assert_called_once()
        self.assertEqual(Question.objects.count(), 3)

    def test_quota_waits_and_preserves_request_budget(self):
        job = self.queue()
        self.process(side_effect=GeminiQuotaExceeded('quota'))
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.provider_calls, 1)
        self.assertGreater(job.next_attempt_at, timezone.now())
        self.assertIsNone(claim_work('ai'))
