"""Exercise question-topic filtering on the database used in production."""

from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from apps.content.models import Department
from .engine import get_topic_questions
from .models import ExamPaper, Question


@skipUnlessDBFeature('supports_json_field_contains')
class TopicDatabaseTests(TestCase):
    def test_topic_selection_matches_complete_tags_and_only_active_papers(self):
        department = Department.objects.create(name='Database Test Department')
        paper = ExamPaper.objects.create(
            title='Topic Test', department=department, exam_type=ExamPaper.TYPE_EXIT_MODEL,
            year=2026, access_level=ExamPaper.ACCESS_FREE,
        )
        matching = Question.objects.create(exam_paper=paper, text='Matching', topic_tags=['Loops'])
        Question.objects.create(exam_paper=paper, text='Different tag', topic_tags=['Nested Loops'])
        Question.objects.create(exam_paper=paper, text='Inactive', topic_tags=['Loops'], is_active=False)
        inactive_paper = ExamPaper.objects.create(
            title='Inactive Paper', department=department, exam_type=ExamPaper.TYPE_EXIT_MODEL,
            year=2025, access_level=ExamPaper.ACCESS_FREE, is_active=False,
        )
        Question.objects.create(exam_paper=inactive_paper, text='Inactive paper', topic_tags=['Loops'])

        questions = get_topic_questions(department.pk, 'Loops', is_premium=True)

        self.assertEqual([question.pk for question in questions], [matching.pk])


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentSimulationTests(TransactionTestCase):
    def test_simulation_can_complete_only_once_on_competing_connections(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        from apps.accounts.models import Student
        from .models import QuizAttempt
        from .services import open_simulation, submit_quiz, SimulationCompleted

        student = Student.objects.create(telegram_id=123458, first_name='Concurrent Quiz')
        paper = ExamPaper.objects.create(title='Concurrent Paper', exam_type='quiz', year=2026)
        question = Question.objects.create(exam_paper=paper, text='Question', option_a='Correct', correct_option='a')
        simulation = open_simulation(student, paper.pk, [question])
        data = {'mode': 'simulation', 'exam_paper_id': paper.pk, 'simulation_id': simulation.pk,
                'selected_topics': [], 'answers': [{'question_id': question.pk, 'selected_option': 'a'}]}
        barrier = Barrier(2)

        def complete():
            try:
                barrier.wait(timeout=10)
                submit_quiz(student, data)
                return 201
            except SimulationCompleted:
                return 409
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(complete) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, [201, 409])
        self.assertEqual(QuizAttempt.objects.filter(student=student).count(), 1)
        simulation.refresh_from_db()
        self.assertIsNotNone(simulation.completed_at)
