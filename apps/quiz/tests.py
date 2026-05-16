from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.content.models import Course
from apps.quiz.engine import get_topics_with_low_score
from apps.quiz.models import ExamPaper, Question, QuizAttempt


class QuizFeedbackApiTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(
            telegram_id=123456789,
            first_name='Quiz',
            username='quizuser',
        )
        self.other_student = Student.objects.create(
            telegram_id=987654321,
            first_name='Other',
            username='otherquizuser',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_generate_jwt(self.student)}')

        self.course = Course.objects.create(
            name='Programming Fundamentals',
            code='CS101',
        )
        self.exam_paper = ExamPaper.objects.create(
            title='Programming Quiz',
            course=self.course,
            exam_type=ExamPaper.TYPE_QUIZ,
            year=2026,
            access_level=ExamPaper.ACCESS_FREE,
        )
        self.first_question = Question.objects.create(
            exam_paper=self.exam_paper,
            text='What is 2 + 2?',
            option_a='3',
            option_b='4',
            option_c='5',
            option_d='6',
            correct_option='b',
            explanation='2 + 2 equals 4.',
            topic_tags=['arithmetic'],
        )
        self.second_question = Question.objects.create(
            exam_paper=self.exam_paper,
            text='Which keyword defines a function in Python?',
            option_a='func',
            option_b='define',
            option_c='def',
            option_d='lambda',
            correct_option='c',
            explanation='Python functions are declared with def.',
            topic_tags=['functions'],
        )

    def test_quiz_submission_stores_and_returns_detailed_answers(self):
        response = self.client.post(
            '/api/quiz/attempts/',
            {
                'course_id': self.course.id,
                'exam_paper_id': self.exam_paper.id,
                'mode': 'practice',
                'answers': [
                    {
                        'question_id': self.first_question.id,
                        'selected_option': 'b',
                    },
                    {
                        'question_id': self.second_question.id,
                        'selected_option': 'a',
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        attempt = QuizAttempt.objects.get(id=response.data['attempt_id'])
        detailed_answers = response.data['detailed_answers']
        first_key = str(self.first_question.id)
        second_key = str(self.second_question.id)

        self.assertEqual(attempt.detailed_answers, detailed_answers)
        self.assertEqual(detailed_answers[first_key]['selected_option'], 'b')
        self.assertEqual(detailed_answers[first_key]['correct_option'], 'b')
        self.assertTrue(detailed_answers[first_key]['is_correct'])
        self.assertEqual(detailed_answers[first_key]['question_text'], 'What is 2 + 2?')
        self.assertEqual(detailed_answers[first_key]['options']['b'], '4')
        self.assertEqual(detailed_answers[first_key]['explanation'], '2 + 2 equals 4.')
        self.assertEqual(detailed_answers[first_key]['topic_tags'], ['arithmetic'])
        self.assertFalse(detailed_answers[second_key]['is_correct'])
        self.assertEqual(attempt.answers, {
            first_key: 'b',
            second_key: 'a',
        })

    def test_feedback_endpoint_returns_attempt_review_summary(self):
        attempt = QuizAttempt.objects.create(
            student=self.student,
            course=self.course,
            exam_paper=self.exam_paper,
            score=1,
            total_questions=2,
            answers={
                str(self.first_question.id): 'b',
                str(self.second_question.id): 'a',
            },
            detailed_answers={
                str(self.first_question.id): {
                    'selected_option': 'b',
                    'correct_option': 'b',
                    'is_correct': True,
                    'question_text': self.first_question.text,
                    'options': self.first_question.available_options,
                    'explanation': self.first_question.explanation,
                    'topic_tags': ['arithmetic'],
                },
                str(self.second_question.id): {
                    'selected_option': 'a',
                    'correct_option': 'c',
                    'is_correct': False,
                    'question_text': self.second_question.text,
                    'options': self.second_question.available_options,
                    'explanation': self.second_question.explanation,
                    'topic_tags': ['functions'],
                },
            },
            mode=QuizAttempt.MODE_PRACTICE,
        )

        response = self.client.get(f'/api/quiz/attempts/{attempt.id}/feedback/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['attempt_id'], attempt.id)
        self.assertEqual(response.data['score'], 1)
        self.assertEqual(response.data['total_questions'], 2)
        self.assertEqual(response.data['percentage'], 50.0)
        self.assertEqual(response.data['summary']['correct'], 1)
        self.assertEqual(response.data['summary']['incorrect'], 1)
        self.assertEqual(response.data['summary']['topics_missed'], [{
            'topic': 'functions',
            'percentage': 0.0,
            'correct': 0,
            'total': 1,
        }])

    def test_feedback_endpoint_is_scoped_to_authenticated_student(self):
        attempt = QuizAttempt.objects.create(
            student=self.other_student,
            score=0,
            total_questions=1,
            answers={str(self.first_question.id): 'a'},
            detailed_answers={},
            mode=QuizAttempt.MODE_PRACTICE,
        )

        response = self.client.get(f'/api/quiz/attempts/{attempt.id}/feedback/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], 'Attempt not found')

    def test_feedback_endpoint_handles_attempts_without_detailed_answers(self):
        attempt = QuizAttempt.objects.create(
            student=self.student,
            score=0,
            total_questions=1,
            answers={str(self.first_question.id): 'a'},
            mode=QuizAttempt.MODE_PRACTICE,
        )

        response = self.client.get(f'/api/quiz/attempts/{attempt.id}/feedback/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detailed_answers'], {})
        self.assertEqual(response.data['summary'], {
            'correct': 0,
            'incorrect': 0,
            'topics_missed': [],
        })


class QuizFeedbackEngineTests(TestCase):
    def test_get_topics_with_low_score_returns_topics_under_fifty_percent(self):
        weak_topics = get_topics_with_low_score({
            '1': {'is_correct': True, 'topic_tags': ['functions', 'syntax']},
            '2': {'is_correct': False, 'topic_tags': ['functions']},
            '3': {'is_correct': False, 'topic_tags': ['data types']},
        })

        self.assertEqual(weak_topics, [{
            'topic': 'data types',
            'percentage': 0.0,
            'correct': 0,
            'total': 1,
        }])
