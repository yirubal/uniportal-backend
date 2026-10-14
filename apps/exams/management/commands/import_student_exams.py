import csv
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.exams.importing import validate_student_rows, write_student_rows
from apps.exams.models import ExamTerm


class Command(BaseCommand):
    help = 'Validate a complete CSV, then atomically import/update attendance for the active term.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file')

    def handle(self, *args, **options):
        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            raise CommandError('No active exam term found.')
        path = Path(options['csv_file'])
        try:
            if path.stat().st_size > settings.MAX_EXAM_PDF_UPLOAD_BYTES:
                raise ValueError('CSV exceeds the import size limit.')
            rows = []
            required = {'date', 'start_time', 'end_time', 'session_number', 'student_name',
                        'student_id', 'department', 'course_name', 'course_code', 'room_code'}
            with path.open(newline='', encoding='utf-8-sig') as source:
                reader = csv.DictReader(source)
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError('CSV is missing required columns.')
                for number, row in enumerate(reader, 2):
                    if len(rows) >= settings.MAX_EXAM_IMPORT_ROWS:
                        raise ValueError('CSV row limit exceeded.')
                    try:
                        rows.append({**{key: row.get(key, '') for key in required},
                                     'date': datetime.strptime(row['date'], '%Y-%m-%d').date(),
                                     'session_number': int(row['session_number']),
                                     'start_time': datetime.strptime(row['start_time'], '%H:%M').time(),
                                     'end_time': datetime.strptime(row['end_time'], '%H:%M').time()})
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f'Invalid date/time/session in CSV row {number}.') from exc
            rows = validate_student_rows(rows)
            created, updated = write_student_rows(term, rows)
        except (OSError, UnicodeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Imported {created} new student exam record(s); updated {updated}.'))
