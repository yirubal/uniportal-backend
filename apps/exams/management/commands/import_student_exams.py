import csv
from datetime import datetime

from django.core.management.base import BaseCommand

from apps.exams.models import ExamSession, ExamTerm, StudentExam


class Command(BaseCommand):
    help = 'Import student exam data from CSV for the active term'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str)

    def handle(self, *args, **options):
        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            self.stdout.write(self.style.ERROR('No active exam term found.'))
            return

        created = 0
        with open(options['csv_file'], newline='', encoding='utf-8') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                date = datetime.strptime(row['date'], '%Y-%m-%d').date()
                start_time = datetime.strptime(row['start_time'], '%H:%M').time()
                end_time = datetime.strptime(row['end_time'], '%H:%M').time()

                session, _ = ExamSession.objects.get_or_create(
                    term=term,
                    session_number=int(row['session_number']),
                    date=date,
                    defaults={'start_time': start_time, 'end_time': end_time},
                )

                _, was_created = StudentExam.objects.get_or_create(
                    term=term,
                    session=session,
                    student_name=row['student_name'].strip(),
                    course_code=row['course_code'].strip(),
                    defaults={
                        'student_id': row['student_id'].strip(),
                        'department': row['department'].strip(),
                        'course_name': row['course_name'].strip(),
                        'room_code': row['room_code'].strip(),
                    },
                )
                if was_created:
                    created += 1

        self.stdout.write(self.style.SUCCESS(f'Imported {created} student exam records.'))
