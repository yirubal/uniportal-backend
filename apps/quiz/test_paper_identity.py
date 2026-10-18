"""Multiple course quizzes keep their own questions and student attempts."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.content.models import Course, Department
from .models import ExamPaper, Question, QuizAttempt


class ExamPaperIdentityTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='Quiz course', code='QUIZ101')
        self.department = Department.objects.create(name='Quiz department')

    def paper_fields(self, **overrides):
        return {
            'title': 'Practice quiz', 'course': self.course, 'department': self.department,
            'exam_type': ExamPaper.TYPE_QUIZ, 'year': 2026,
            'duration_minutes': 30, 'access_level': ExamPaper.ACCESS_FREE, **overrides,
        }

    def test_quizzes_with_identical_metadata_pass_validation_and_database_insert(self):
        for department in (None, self.department):
            with self.subTest(department=department):
                fields = self.paper_fields(department=department)
                first = ExamPaper.objects.create(**fields)
                second = ExamPaper(**fields)
                second.full_clean()
                second.save()
                self.assertNotEqual(first.pk, second.pk)

    def test_admin_can_add_multiple_quizzes_for_same_course_and_year(self):
        admin = get_user_model().objects.create_user('quiz-admin', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        for title in ('Chapter 1 practice', 'Chapter 2 practice'):
            response = self.client.post('/admin/quiz/exampaper/add/', {
                'title': title, 'course': self.course.pk, 'department': self.department.pk,
                'exam_type': ExamPaper.TYPE_QUIZ, 'year': 2026,
                'duration_minutes': 30, 'access_level': ExamPaper.ACCESS_FREE,
                'is_active': 'on', '_save': 'Save',
            })
            self.assertEqual(response.status_code, 302)
        self.assertEqual(ExamPaper.objects.filter(course=self.course, year=2026).count(), 2)

    def test_non_quiz_identity_still_rejects_duplicates(self):
        for exam_type in (ExamPaper.TYPE_FINAL, ExamPaper.TYPE_EXIT_REAL, ExamPaper.TYPE_EXIT_MODEL):
            with self.subTest(exam_type=exam_type):
                fields = self.paper_fields(exam_type=exam_type)
                ExamPaper.objects.create(**fields)
                duplicate = ExamPaper(**{**fields, 'title': 'A different title'})
                with self.assertRaises(ValidationError):
                    duplicate.full_clean()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    duplicate.save()
                next_year = ExamPaper(**{**fields, 'year': 2027})
                next_year.full_clean()
                next_year.save()

    def test_non_quiz_nullable_identity_keeps_previous_null_semantics(self):
        # The old four-column unique_together permitted duplicates with a NULL
        # course/department. This change must not tighten rules on existing data.
        for exam_type, changes in (
            (ExamPaper.TYPE_FINAL, {'department': None}),
            (ExamPaper.TYPE_EXIT_REAL, {'course': None}),
            (ExamPaper.TYPE_EXIT_MODEL, {'course': None}),
        ):
            with self.subTest(exam_type=exam_type):
                fields = self.paper_fields(exam_type=exam_type, **changes)
                ExamPaper.objects.create(**fields)
                duplicate = ExamPaper(**fields)
                duplicate.full_clean()
                duplicate.save()

    def test_api_lists_both_quizzes_and_keeps_questions_and_attempts_separate(self):
        student = Student.objects.create(telegram_id=551234, first_name='Quiz learner')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(student))
        papers = [ExamPaper.objects.create(**self.paper_fields(title=title))
                  for title in ('Chapter 1 practice', 'Chapter 2 practice')]
        questions = [Question.objects.create(exam_paper=paper, text=paper.title,
                     option_a='Correct', option_b='Wrong', correct_option='a') for paper in papers]
        response = client.get('/api/exams/', {'course': self.course.pk, 'type': 'quiz'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row['id'] for row in response.data}, {paper.pk for paper in papers})
        for paper, question in zip(papers, questions):
            response = client.get(f'/api/exams/{paper.pk}/questions/', {'mode': 'practice'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row['id'] for row in response.data], [question.pk])
            response = client.post('/api/quiz/attempts/', {
                'exam_paper_id': paper.pk,
                'answers': [{'question_id': question.pk, 'selected_option': 'a'}],
            }, format='json')
            self.assertEqual(response.status_code, 201)
            attempt = QuizAttempt.objects.get(student=student, exam_paper=paper)
            self.assertEqual(attempt.score, 1)
        self.assertEqual(QuizAttempt.objects.filter(student=student).count(), 2)
