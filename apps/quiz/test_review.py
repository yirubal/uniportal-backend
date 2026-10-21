from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.bot.models import QuestionExtraction
from apps.content.models import Course, Department, Resource
from .models import Chapter, ExamPaper, Question
from .review import quality_flags, suggest_chapter


class PaperReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('review-admin')
        self.client.force_login(self.user)
        self.course = Course.objects.create(name='Management', code='MAN')
        self.chapter = Chapter.objects.create(course=self.course, title='Leadership', number=1)
        self.gap = Chapter.objects.create(course=self.course, title='Planning', number=2)
        self.paper = ExamPaper.objects.create(title='Practice draft', course=self.course, exam_type='quiz', year=2026, is_active=False)
        self.question = self.make_question('What is leadership?')
        self.url = reverse('admin:quiz_exampaper_review_questions', args=[self.paper.pk])

    def make_question(self, text, **values):
        return Question.objects.create(**{'text': text, 'exam_paper': self.paper, 'is_active': False,
            'question_type': 'mcq', 'option_a': 'Guiding people', 'option_b': 'Avoiding goals',
            'correct_option': 'a', 'explanation': 'Leadership guides people.', **values})

    def token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context['form']['selection'].value()

    def apply(self, token=None, **values):
        return self.client.post(self.url, {'selection': token or self.token(), 'selected': [self.question.pk],
            'action': 'activate', 'reviewed': 'on', **values})

    def test_review_shows_answers_options_coverage_and_explicit_title_match(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Guiding people')
        self.assertContains(response, 'Leadership guides people.')
        self.assertContains(response, 'Title-word match suggests')
        self.assertEqual(response.context['cards'][0]['suggestion'], self.chapter)
        self.assertEqual([(c.total, c.active) for c in response.context['coverage']], [(0, 0), (0, 0)])
        self.assertContains(self.client.get(reverse('admin:quiz_exampaper_change', args=[self.paper.pk])),
                            'Review questions &amp; chapter coverage')
        self.question.refresh_from_db()
        self.assertIsNone(self.question.chapter_id)
        self.assertFalse(self.question.is_active)

    def test_explicit_activation_updates_selected_only_and_logs_without_publishing_paper(self):
        other = self.make_question('What is planning?')
        with patch('apps.bot.generation._request_question_json') as provider:
            self.assertEqual(self.apply().status_code, 302)
            provider.assert_not_called()
        self.question.refresh_from_db()
        other.refresh_from_db()
        self.paper.refresh_from_db()
        self.assertTrue(self.question.is_active)
        self.assertFalse(other.is_active)
        self.assertFalse(self.paper.is_active)
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.question.pk), change_message__contains='paper review').exists())

    def test_answer_confirmation_and_quality_blockers_prevent_partial_activation(self):
        bad = self.make_question('Question with no answer', correct_option='')
        token = self.token()
        for changes in ({'reviewed': ''}, {'selected': [self.question.pk, bad.pk]}):
            response = self.apply(token, **changes)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['errors'])
        self.assertFalse(self.paper.questions.filter(is_active=True).exists())

    def test_duplicate_text_and_options_block_activation(self):
        self.make_question('  WHAT IS LEADERSHIP?  ')
        response = self.apply()
        self.assertContains(response, 'Another question in this paper')
        self.question.refresh_from_db()
        self.assertFalse(self.question.is_active)
        self.question.option_b = self.question.option_a
        self.assertTrue(any('distinct options' in issue for issue in quality_flags(self.question, set())[0]))

    def test_chapter_saving_replaces_old_chapter_tag_preserves_topics_and_does_not_activate(self):
        self.question.chapter = self.gap
        self.question.topic_tags = ['Chapter 2: Planning', 'teamwork']
        self.question.save(update_fields=['chapter', 'topic_tags'])
        self.assertEqual(self.apply(action='chapters', **{f'chapter_{self.question.pk}': self.chapter.pk}).status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.chapter_id, self.chapter.pk)
        self.assertEqual(self.question.topic_tags, ['teamwork', 'Chapter 1: Leadership'])
        self.assertFalse(self.question.is_active)
        self.assertEqual(self.client.get(self.url).context['coverage'][0].total, 1)

    def test_foreign_course_and_inactive_chapters_are_rejected(self):
        other_course = Course.objects.create(name='Other', code='OTHER')
        other = Chapter.objects.create(course=other_course, title='Other', number=1)
        Chapter.objects.filter(pk=self.gap.pk).update(is_active=False)
        for chapter in (other, self.gap):
            with self.subTest(chapter=chapter):
                self.assertEqual(self.apply(action='chapters', **{f'chapter_{self.question.pk}': chapter.pk}).status_code, 200)
        self.question.refresh_from_db()
        self.assertIsNone(self.question.chapter_id)

    def test_changed_deleted_or_moved_questions_cannot_be_approved_from_stale_page(self):
        token = self.token()
        Question.objects.filter(pk=self.question.pk).update(correct_option='b')
        self.assertContains(self.apply(token), 'Questions changed since this page')
        self.question.refresh_from_db()
        self.assertFalse(self.question.is_active)
        token = self.token()
        self.question.delete()
        response = self.apply(token, selected=['1'])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Question.objects.filter(is_active=True).exists())

    def test_cross_paper_injection_and_other_admin_token_are_rejected(self):
        other_paper = ExamPaper.objects.create(title='Other', course=self.course, exam_type='quiz', year=2026)
        foreign = self.make_question('Foreign question', exam_paper=other_paper)
        token = self.token()
        self.assertEqual(self.apply(token, selected=[foreign.pk]).status_code, 200)
        self.assertEqual(self.apply(token + 'tampered').status_code, 302)
        another_admin = get_user_model().objects.create_superuser('another-review-admin')
        self.client.force_login(another_admin)
        self.assertEqual(self.apply(token).status_code, 302)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_active)

    def test_paper_visibility_change_requires_a_fresh_review(self):
        token = self.token()
        ExamPaper.objects.filter(pk=self.paper.pk).update(is_active=True)
        self.assertContains(self.apply(token), 'Questions changed since this page')
        self.question.refresh_from_db()
        self.assertFalse(self.question.is_active)

    def test_permission_scopes_hide_chapters_sources_and_allow_question_review_without_add(self):
        user = get_user_model().objects.create_user('review-only', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        user.user_permissions.add(*Permission.objects.filter(codename__in=['view_exampaper', 'change_question']))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_chapters'])
        self.assertFalse(response.context['can_view_jobs'])
        self.assertFalse(response.context['coverage'])
        self.assertContains(self.client.get(reverse('admin:quiz_exampaper_change', args=[self.paper.pk])),
                            'Review questions &amp; chapter coverage')
        self.assertEqual(self.apply(action='chapters', **{f'chapter_{self.question.pk}': self.chapter.pk}).status_code, 200)
        self.question.refresh_from_db()
        self.assertIsNone(self.question.chapter_id)

    def test_generation_source_excerpt_is_rechecked_and_snapshot_link_is_permission_gated(self):
        job = QuestionExtraction.objects.create(mode='generate', exam_paper=self.paper, source_hash='x',
            version='v1', source_text='Leadership involves guiding people toward common goals.', source_label='Notes')
        self.question.source_extraction = job
        self.question.source_quote = 'A made-up quotation.'
        self.question.save(update_fields=['source_extraction', 'source_quote'])
        response = self.apply()
        self.assertContains(response, 'no longer matches the saved source')
        self.question.refresh_from_db()
        self.assertFalse(self.question.is_active)
        self.question.source_quote = job.source_text
        self.question.save(update_fields=['source_quote'])
        self.assertEqual(self.apply().status_code, 302)

    def test_revision_shortcut_prefills_generation_but_does_not_queue_or_move_questions(self):
        resource = Resource.objects.create(title='Notes', extracted_text='Leadership and planning guide teams. ' * 10)
        QuestionExtraction.objects.create(mode='generate', exam_paper=self.paper, resource=resource,
            source_hash='x', version='v1', source_text=resource.extracted_text)
        response = self.client.get(self.url)
        url = response.context['coverage'][1].revision_url
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params['focus'], ['Planning'])
        form = self.client.get(url).context['form']
        self.assertEqual(str(form['resource'].value()), str(resource.pk))
        self.assertEqual(str(form['chapter'].value()), str(self.gap.pk))
        self.assertEqual(form['focus'].value(), 'Planning')
        self.assertEqual(QuestionExtraction.objects.count(), 1)
        self.assertEqual(ExamPaper.objects.count(), 1)

    def test_department_wide_paper_has_no_course_coverage(self):
        self.paper.course = None
        self.paper.department = Department.objects.create(name='Management department')
        self.paper.exam_type = 'exit_model'
        self.paper.save(update_fields=['course', 'department', 'exam_type'])
        self.assertContains(self.client.get(self.url), 'Department-wide papers have no course chapters')

    def test_pagination_limits_review_payload_and_cannot_activate_a_hidden_row(self):
        for number in range(26):
            self.make_question(f'Question {number}')
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['cards']), 25)
        hidden = self.paper.questions.order_by('pk').last()
        self.assertEqual(self.apply(response.context['form']['selection'].value(), selected=[hidden.pk]).status_code, 200)
        hidden.refresh_from_db()
        self.assertFalse(hidden.is_active)

    def test_ambiguous_chapter_title_match_does_not_guess(self):
        same_title = Chapter.objects.create(course=self.course, title='Leadership basics', number=3)
        self.assertIsNone(suggest_chapter(self.question, [self.chapter, same_title]))

    def test_review_query_count_does_not_grow_for_each_question(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for number in range(24):
            self.make_question(f'Leadership review question {number}')
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url)
        self.assertLessEqual(len(large), len(small) + 2)

    def test_manual_marking_types_and_unsupported_shapes(self):
        for kind in ('essay', 'matching', 'true_false', 'fill_blank'):
            question = self.make_question(kind, question_type=kind)
            with self.subTest(kind=kind):
                self.assertTrue(quality_flags(question, set())[0])
        essay = self.make_question('Explain leadership.', question_type='essay', option_a='', option_b='', correct_option='')
        blockers, warnings = quality_flags(essay, set())
        self.assertFalse(blockers)
        self.assertIn('Student responses require manual marking.', warnings)
