from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.quiz.importers import import_exit_questions_from_excel
from apps.quiz.models import ExamPaper


class Command(BaseCommand):
    help = 'Import exit exam questions; course and chapter are optional'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, required=True, help='Path to the Excel file')
        parser.add_argument('--exam-paper-id', type=int, required=True,
                            help='Exit ExamPaper ID to link imported questions to')
        parser.add_argument('--delete-existing', action='store_true',
                            help='Replace existing questions if at least one new question imports successfully')

    def handle(self, *args, **options):
        try:
            paper = ExamPaper.objects.get(pk=options['exam_paper_id'])
        except ExamPaper.DoesNotExist as exc:
            raise CommandError(f"Exam paper not found: {options['exam_paper_id']}") from exc
        if not paper.is_exit_exam:
            raise CommandError(f'Exam paper {paper.pk} is not an exit exam.')

        try:
            with open(options['file'], 'rb') as excel_file, transaction.atomic():
                if options['delete_existing']:
                    paper.questions.all().delete()
                # Preserve this command's existing activation behavior. Admin
                # uploads use the importer's default: inactive pending review.
                result = import_exit_questions_from_excel(excel_file, paper, is_active=True)
                if not result.created:
                    self._write_errors(result.errors)
                    raise CommandError('No questions were imported.')
        except OSError as exc:
            raise CommandError(f'Could not read Excel file: {exc}') from exc

        self.stdout.write(self.style.SUCCESS('Import complete'))
        self.stdout.write(f'  Exam: {paper.title}')
        self.stdout.write(f'  Questions created: {result.created}')
        self.stdout.write(f'  Questions skipped: {result.skipped}')
        self._write_errors(result.errors)

    def _write_errors(self, errors):
        if errors:
            self.stdout.write(self.style.WARNING('Errors:'))
            for error in errors[:20]:
                self.stdout.write(f'  {error}')
            if len(errors) > 20:
                self.stdout.write(f'  ... and {len(errors) - 20} more')
