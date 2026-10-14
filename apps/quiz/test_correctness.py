from datetime import timedelta
import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.content.models import Course, Department
from .engine import get_performance_summary
from .models import ExamPaper, Question, QuizAttempt, QuizSimulation


class QuizCorrectnessTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(telegram_id=555001, first_name='Quiz Test')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(self.student))
        self.course = Course.objects.create(name='Test Course', code='TEST')
        self.paper = ExamPaper.objects.create(
            title='Test Paper', course=self.course, exam_type='quiz', year=2026,
            duration_minutes=30, access_level='free',
        )
        self.question = Question.objects.create(
            exam_paper=self.paper, text='First question', option_a='Correct', option_b='Wrong',
            correct_option='a', topic_tags=['Original topic'],
        )
        self.second = Question.objects.create(
            exam_paper=self.paper, text='Second question', option_a='Correct', correct_option='a',
        )

    def submit(self, **changes):
        data = {
            'exam_paper_id': self.paper.pk,
            'answers': [{'question_id': self.question.pk, 'selected_option': 'a'}],
        }
        data.update(changes)
        return self.client.post('/api/quiz/attempts/', data, format='json')

    def open_simulation(self):
        response = self.client.get(f'/api/exams/{self.paper.pk}/questions/?mode=simulation')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertNotIn('correct_option', response.data[0])
        return response.headers['X-Quiz-Simulation-ID']

    def test_invalid_selection_inputs_return_400(self):
        for params in ('limit=abc', 'limit=0', 'limit=-1', 'limit=501', 'mode=unknown'):
            with self.subTest(params=params):
                response = self.client.get(f'/api/exams/{self.paper.pk}/questions/?{params}')
                self.assertEqual(response.status_code, 400)
        response = self.client.get('/api/exit-exams/topics/questions/?department=abc&topic=Loops')
        self.assertEqual(response.status_code, 400)

    def test_invalid_answer_shapes_modes_and_ids_do_not_create_attempts(self):
        for changes in (
            {'answers': 'not a list'}, {'answers': [1]},
            {'answers': [{'selected_option': 'a'}]},
            {'answers': [{'question_id': self.question.pk, 'selected_option': {}}]},
            {'answers': [{'question_id': self.question.pk}, {'question_id': self.question.pk}]},
            {'answers': [{'question_id': 999999, 'selected_option': 'a'}]},
            {'answers': [{'question_id': self.question.pk, 'selected_option': 'e'}]},
            {'mode': 'unknown'}, {'course_id': 999999}, {'department_id': 999999},
            {'answers': [{'question_id': self.question.pk}] * 501},
        ):
            with self.subTest(changes=str(changes)[:100]):
                self.assertEqual(self.submit(**changes).status_code, 400)
        self.assertFalse(QuizAttempt.objects.exists())

    def test_wrong_quiz_context_and_selected_topics_are_rejected(self):
        other_course = Course.objects.create(name='Other Course', code='OTHER')
        self.assertEqual(self.submit(course_id=other_course.pk).status_code, 400)
        department = Department.objects.create(name='Unrelated Department')
        self.assertEqual(self.submit(department_id=department.pk).status_code, 400)
        self.assertEqual(self.submit(
            mode='selective', course_id=self.course.pk, selected_topics=['Different topic'],
        ).status_code, 400)

    def test_mixed_question_scores_agree_in_submission_feedback_history_and_performance(self):
        essay = Question.objects.create(exam_paper=self.paper, text='Essay', question_type='essay', topic_tags=['Essay topic'])
        matching = Question.objects.create(exam_paper=self.paper, text='Matching', question_type='matching', topic_tags=['Matching topic'])
        response = self.submit(answers=[
            {'question_id': self.question.pk, 'selected_option': 'a'},
            {'question_id': essay.pk, 'selected_option': 'Essay answer'},
            {'question_id': matching.pk, 'selected_option': 'Pairs'},
        ])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['percentage'], 100)
        attempt = QuizAttempt.objects.get(pk=response.data['attempt_id'])
        self.assertEqual((attempt.gradable_total, attempt.pending_count, attempt.percentage), (1, 2, 100))
        self.assertFalse(matching.is_auto_gradable)
        feedback = self.client.get(f'/api/quiz/attempts/{attempt.pk}/feedback/').data
        self.assertEqual(feedback['percentage'], 100)
        self.assertEqual(feedback['summary']['incorrect'], 0)
        self.assertEqual(feedback['summary']['topics_missed'], [])
        history = self.client.get('/api/quiz/attempts/').data
        self.assertEqual(history[0]['percentage'], 100)
        summary = get_performance_summary(self.student)
        self.assertEqual(summary['average_score'], 100)
        self.assertEqual(summary['attempts_by_paper'][0]['average'], 100)

    def test_unanswered_simulation_questions_count_and_completion_is_once_only(self):
        simulation_id = self.open_simulation()
        self.assertEqual(self.open_simulation(), simulation_id)
        response = self.submit(mode='simulation', simulation_id=simulation_id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data['total'], response.data['gradable_total'], response.data['percentage']), (2, 2, 50))
        self.assertTrue(response.data['detailed_answers'][str(self.second.pk)]['is_unanswered'])
        self.assertEqual(self.submit(mode='simulation', simulation_id=simulation_id).status_code, 409)
        self.assertEqual(self.submit(mode='simulation').status_code, 409)
        self.assertEqual(QuizAttempt.objects.count(), 1)
        self.assertNotEqual(self.open_simulation(), simulation_id)

    def test_empty_simulation_submission_scores_all_questions_as_unanswered(self):
        self.open_simulation()
        response = self.submit(mode='simulation', answers=[])
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data['total'], response.data['score']), (2, 0))

    def test_simulation_scores_snapshot_after_questions_are_edited_or_deleted(self):
        simulation_id = self.open_simulation()
        self.question.correct_option = 'b'
        self.question.text = 'Edited'
        self.question.save()
        self.second.delete()
        response = self.submit(mode='simulation', simulation_id=simulation_id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data['score'], response.data['total']), (1, 2))
        self.assertEqual(response.data['detailed_answers'][str(self.question.pk)]['question_text'], 'First question')

    def test_unissued_expired_or_another_students_simulation_is_rejected(self):
        self.assertEqual(self.submit(mode='simulation').status_code, 400)
        simulation_id = self.open_simulation()
        extra = Question.objects.create(exam_paper=self.paper, text='Not issued', option_a='A', correct_option='a')
        self.assertEqual(self.submit(mode='simulation', answers=[{'question_id': extra.pk, 'selected_option': 'a'}]).status_code, 400)
        other = Student.objects.create(telegram_id=555002, first_name='Other')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(other))
        self.assertEqual(self.submit(mode='simulation', simulation_id=simulation_id).status_code, 400)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(self.student))
        QuizSimulation.objects.filter(pk=simulation_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.submit(mode='simulation', simulation_id=simulation_id).status_code, 400)
        self.assertFalse(QuizAttempt.objects.exists())

    def test_historical_topics_survive_question_edits_and_deletion(self):
        response = self.submit(answers=[{'question_id': self.question.pk, 'selected_option': 'b'}])
        self.assertEqual(response.status_code, 201)
        self.question.topic_tags = ['Changed topic']
        self.question.save()
        self.question.delete()
        self.assertEqual(get_performance_summary(self.student)['weak_topics'], ['Original topic'])

    def test_legacy_backfill_uses_complete_snapshots_and_preserves_unknown_denominators(self):
        known = QuizAttempt.objects.create(
            student=self.student, score=1, total_questions=2,
            detailed_answers={'1': {'question_type': 'mcq'}, '2': {'question_type': 'essay'}},
        )
        unknown = QuizAttempt.objects.create(student=self.student, score=1, total_questions=2)
        migration = importlib.import_module('apps.quiz.migrations.0010_backfill_attempt_denominators')
        migration.backfill_attempt_denominators(apps, SimpleNamespace(connection=connection))
        known.refresh_from_db()
        unknown.refresh_from_db()
        self.assertEqual((known.gradable_total, known.pending_count, known.percentage), (1, 1, 100))
        self.assertIsNone(unknown.gradable_total)
        self.assertEqual(unknown.percentage, 50)
