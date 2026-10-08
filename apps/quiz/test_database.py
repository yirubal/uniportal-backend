"""Exercise question-topic filtering on the database used in production."""

from django.test import TestCase, skipUnlessDBFeature

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
