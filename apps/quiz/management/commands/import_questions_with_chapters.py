from django.core.management.base import BaseCommand, CommandError

from apps.content.models import Course
from apps.quiz.importers import import_questions_from_excel
from apps.quiz.models import ExamPaper


class Command(BaseCommand):
    help = 'Import questions from an Excel file with required chapter mapping'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to the Excel file')
        parser.add_argument(
            '--exam-paper-id',
            type=int,
            required=True,
            help='ExamPaper ID to link questions to',
        )
        parser.add_argument(
            '--course-id',
            type=int,
            required=True,
            help='Course ID used to validate the exam paper course',
        )

    def handle(self, *args, **options):
        file_path = options['file_path']
        exam_paper_id = options['exam_paper_id']
        course_id = options['course_id']

        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist as exc:
            raise CommandError(f'Active course not found: {course_id}') from exc

        try:
            exam_paper = ExamPaper.objects.get(id=exam_paper_id)
        except ExamPaper.DoesNotExist as exc:
            raise CommandError(f'Exam paper not found: {exam_paper_id}') from exc

        if exam_paper.course_id != course.id:
            raise CommandError(
                f'Exam paper {exam_paper.id} is not linked to course {course.id}. '
                'Create or update the exam paper for this course before importing.'
            )

        try:
            with open(file_path, 'rb') as excel_file:
                result = import_questions_from_excel(excel_file, exam_paper)
        except FileNotFoundError as exc:
            raise CommandError(f'File not found: {file_path}') from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Import complete for {course.code} — {course.name}'
            )
        )
        self.stdout.write(f'  Created: {result.created}')
        self.stdout.write(f'  Skipped: {result.skipped}')

        if result.errors:
            self.stdout.write(self.style.WARNING('Errors:'))
            for error in result.errors:
                self.stdout.write(f'  {error}')

        if result.created == 0 and result.errors:
            raise CommandError('No questions were imported.')
