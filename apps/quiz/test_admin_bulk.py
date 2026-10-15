from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.content.models import Course
from .models import Chapter, ExamPaper, Question


@override_settings(ALLOWED_HOSTS=['testserver'])
class QuestionBulkEditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('question-editor')
        self.client.force_login(self.user)
        self.course = Course.objects.create(name='Computing', code='CS')
        self.other = Course.objects.create(name='Business', code='BUS')
        self.paper = ExamPaper.objects.create(title='Computing paper', course=self.course, exam_type='final', year=2018)
        self.chapter = Chapter.objects.create(course=self.course, number=1, title='Basics')
        self.other_chapter = Chapter.objects.create(course=self.other, number=1, title='Business basics')
        self.one = Question.objects.create(text='Question one', is_active=False)
        self.two = Question.objects.create(text='Question two', is_active=False)

    def selection(self, *questions, action='bulk_set_metadata'):
        response = self.client.post(reverse('admin:quiz_question_changelist'), {
            'action': action, '_selected_action': [question.pk for question in questions], 'index': 0,
        })
        self.assertEqual(response.status_code, 200)
        return response.context['form']['selection'].value()

    def apply(self, token, **values):
        return self.client.post(reverse('admin:quiz_question_bulk_metadata'), {'selection': token, **values})

    def test_tabs_keep_independent_signed_selections(self):
        first, second = self.selection(self.one), self.selection(self.two)
        self.assertEqual(self.apply(first, difficulty='hard', year_source='2018 EC').status_code, 302)
        self.assertEqual(self.apply(second, difficulty='easy').status_code, 302)
        self.one.refresh_from_db(); self.two.refresh_from_db()
        self.assertEqual(self.one.difficulty, 'hard')
        self.assertEqual(self.one.year_source, '2018 EC')
        self.assertEqual(self.two.difficulty, 'easy')

    def test_invalid_choices_ids_and_lengths_preserve_input_and_make_no_updates(self):
        token = self.selection(self.one, self.two)
        for values in [{'difficulty': 'impossible'}, {'exam_paper': 999999},
                       {'year_source': 'a' * 11}, {'is_active': 'invalid'}]:
            response = self.apply(token, **values)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
            self.assertEqual(response.context['form']['selection'].value(), token)
        self.one.refresh_from_db()
        self.assertEqual(self.one.difficulty, 'medium')
        self.assertFalse(self.one.is_active)

    def test_effective_paper_chapter_relationship_is_validated_atomically(self):
        self.two.chapter = self.other_chapter
        self.two.save(update_fields=['chapter'])
        token = self.selection(self.one, self.two)
        response = self.apply(token, exam_paper=self.paper.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.one.refresh_from_db()
        self.assertIsNone(self.one.exam_paper_id)
        self.assertEqual(self.apply(token, exam_paper=self.paper.pk, clear_chapter='on').status_code, 302)
        self.two.refresh_from_db()
        self.assertEqual(self.two.exam_paper_id, self.paper.pk)
        self.assertIsNone(self.two.chapter_id)

    def test_tampered_and_other_user_selections_cannot_edit_questions(self):
        token = self.selection(self.one)
        self.assertEqual(self.apply(token + 'tampered', is_active='true').status_code, 302)
        other = get_user_model().objects.create_superuser('other-editor')
        self.client.force_login(other)
        self.assertEqual(self.apply(token, is_active='true').status_code, 302)
        self.one.refresh_from_db()
        self.assertFalse(self.one.is_active)

    def test_deleted_selection_member_blocks_partial_updates(self):
        token = self.selection(self.one, self.two)
        self.two.delete()
        response = self.apply(token, difficulty='hard')
        self.assertEqual(response.status_code, 200)
        self.one.refresh_from_db()
        self.assertEqual(self.one.difficulty, 'medium')

    def test_related_choices_do_not_expose_models_the_editor_cannot_view(self):
        user = get_user_model().objects.create_user('metadata-only', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='change_question'))
        self.client.force_login(user)
        token = self.selection(self.one)
        response = self.apply(token, exam_paper=self.paper.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn('exam_paper', response.context['form'].errors)
        self.assertEqual(self.apply(token, difficulty='hard').status_code, 302)

    def test_assignment_action_uses_the_same_validated_form(self):
        token = self.selection(self.one, action='assign_to_exam_paper')
        self.assertEqual(self.apply(token).status_code, 200)
        self.assertEqual(self.apply(token, exam_paper=self.paper.pk, chapter=self.chapter.pk).status_code, 302)
        self.one.refresh_from_db()
        self.assertEqual(self.one.exam_paper_id, self.paper.pk)
        self.assertEqual(self.one.chapter_id, self.chapter.pk)
