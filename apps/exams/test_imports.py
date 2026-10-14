import csv
from datetime import date, time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from .importing import validate_student_rows, write_student_rows
from .models import ExamPDFUpload, ExamScheduleEntry, ExamSession, ExamTerm, StudentExam
from .parsers.attendance_parser import ParsedAttendancePDF, ParsedStudent
from .parsers.schedule_parser import ParsedSchedule, ParsedScheduleSession, ParsedScheduleEntry
from .services import process_attendance_pdf, process_schedule_pdf


def student_row(**changes):
    row = {'session_number': 1, 'date': date(2026, 10, 20), 'start_time': time(8), 'end_time': time(10),
           'student_name': 'Test Student', 'student_id': 'id123', 'department': 'Business',
           'course_name': 'Accounting', 'course_code': 'acct101', 'room_code': 'R-1'}
    row.update(changes)
    return row


class ExamImportTests(TestCase):
    def setUp(self):
        self.term = ExamTerm.objects.create(year=2019, term=1, is_active=True)

    def upload(self, kind):
        return ExamPDFUpload.objects.create(pdf_type=kind, original_name='test.pdf',
            file=SimpleUploadedFile('test.pdf', b'%PDF synthetic import'))

    def test_reimport_is_idempotent_and_matching_id_corrects_metadata(self):
        self.assertEqual(write_student_rows(self.term, [student_row()]), (1, 0))
        self.assertEqual(write_student_rows(self.term, [student_row()]), (0, 0))
        self.assertEqual(write_student_rows(self.term, [student_row(student_name='Corrected Name', department='Corrected')]), (0, 1))
        self.assertEqual(StudentExam.objects.count(), 1)
        student = StudentExam.objects.get()
        self.assertEqual(student.student_id, 'ID123')
        self.assertEqual(student.course_code, 'ACCT 101')
        self.assertEqual(student.student_name, 'Corrected Name')

    def test_unknown_ids_use_name_identity_and_rooms_remain_distinct(self):
        rows = [student_row(student_id=''), student_row(student_id='', room_code='R-2')]
        self.assertEqual(write_student_rows(self.term, rows), (2, 0))
        self.assertEqual(write_student_rows(self.term, rows), (0, 0))

    def test_invalid_last_row_and_conflicting_duplicates_make_no_partial_import(self):
        for rows in [[student_row(), student_row(student_id='second', end_time=time(7))],
                     [student_row(), student_row(department='Contradiction')],
                     [student_row(course_code='')]]:
            with self.assertRaises(ValueError):
                write_student_rows(self.term, rows)
            self.assertFalse(ExamSession.objects.exists())
            self.assertFalse(StudentExam.objects.exists())

    def test_conflicting_existing_session_times_do_not_overwrite_other_exams(self):
        write_student_rows(self.term, [student_row()])
        with self.assertRaisesMessage(ValueError, 'correct the session explicitly'):
            write_student_rows(self.term, [student_row(student_id='new', start_time=time(9))])
        self.assertEqual(StudentExam.objects.count(), 1)
        self.assertEqual(ExamSession.objects.get().start_time, time(8))

    def test_failed_bulk_update_rolls_back_new_rows_and_corrections(self):
        write_student_rows(self.term, [student_row()])
        with patch.object(StudentExam.objects, 'bulk_update', side_effect=RuntimeError('Database failed')):
            with self.assertRaises(RuntimeError):
                write_student_rows(self.term, [student_row(department='Changed'), student_row(student_id='new')])
        self.assertEqual(StudentExam.objects.count(), 1)
        self.assertEqual(StudentExam.objects.get().department, 'Business')

    def test_schedule_reimports_update_details_once(self):
        upload = self.upload('schedule')
        entry = ParsedScheduleEntry('Accounting', 'acct101', 20, ['R-1'])
        parsed = ParsedSchedule(2019, 1, 'Addis Ababa', [ParsedScheduleSession(1, date(2026, 10, 20), time(8), time(10), [entry])])
        with patch('apps.exams.parsers.schedule_parser.parse_schedule_pdf', return_value=parsed):
            self.assertEqual(process_schedule_pdf(upload)[:2], (True, 1))
            self.assertEqual(process_schedule_pdf(upload)[:2], (True, 0))
            entry.total_students = 25
            self.assertEqual(process_schedule_pdf(upload)[:2], (True, 0))
        self.assertEqual(ExamScheduleEntry.objects.count(), 1)
        self.assertEqual(ExamScheduleEntry.objects.get().total_students, 25)
        upload.refresh_from_db()
        self.assertEqual(upload.records_updated, 1)

    def test_invalid_schedule_does_not_create_its_term_or_first_session(self):
        upload = self.upload('schedule')
        valid = ParsedScheduleEntry('Accounting', 'ACCT 101', 20, ['R-1'])
        invalid = ParsedScheduleEntry('', 'ACCT 102', 20, ['R-1'])
        parsed = ParsedSchedule(2020, 1, 'Addis Ababa', [ParsedScheduleSession(1, date(2026, 10, 20), time(8), time(10), [valid, invalid])])
        with patch('apps.exams.parsers.schedule_parser.parse_schedule_pdf', return_value=parsed):
            success, _, error = process_schedule_pdf(upload)
        self.assertFalse(success)
        self.assertTrue(error)
        self.assertFalse(ExamTerm.objects.filter(year=2020).exists())
        self.assertFalse(ExamSession.objects.exists())

    def test_attendance_all_blocks_validate_before_writing(self):
        upload = self.upload('attendance')
        block = ParsedAttendancePDF(2020, 1, date(2026, 10, 20), 1, time(8), time(10), 'R-1',
                                    'Accounting', 'ACCT 101', [ParsedStudent('Test', 'ID123', 'Business')])
        bad = ParsedAttendancePDF(2020, 2, date(2026, 10, 20), 1, time(8), time(10), 'R-1',
                                    'Accounting', 'ACCT 101', [ParsedStudent('Other', 'ID124', 'Business')])
        with patch('apps.exams.parsers.attendance_parser.parse_attendance_pdf', return_value=[block, bad]):
            self.assertFalse(process_attendance_pdf(upload)[0])
        self.assertFalse(ExamTerm.objects.filter(year=2020).exists())
        with patch('apps.exams.parsers.attendance_parser.parse_attendance_pdf', return_value=[block]):
            self.assertEqual(process_attendance_pdf(upload)[:2], (True, 1))
            self.assertEqual(process_attendance_pdf(upload)[:2], (True, 0))

    def test_csv_validates_last_row_before_any_write(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'roster.csv'
            rows = [student_row(), student_row(student_id='new', student_name='')]
            for row in rows:
                row['date'] = row['date'].isoformat()
                row['start_time'] = '08:00'
                row['end_time'] = '10:00'
            with path.open('w', newline='') as source:
                writer = csv.DictWriter(source, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(CommandError):
                call_command('import_student_exams', str(path), stdout=StringIO())
        self.assertFalse(StudentExam.objects.exists())
        self.assertFalse(ExamSession.objects.exists())


class ExamIdentityMigrationTests(TransactionTestCase):
    def test_migration_removes_exact_duplicates_and_refuses_conflicting_payloads(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('exams', '0006_alter_exampdfupload_file')])
        historical = executor.loader.project_state([('exams', '0006_alter_exampdfupload_file')]).apps
        Term = historical.get_model('exams', 'ExamTerm')
        Session = historical.get_model('exams', 'ExamSession')
        Exam = historical.get_model('exams', 'StudentExam')
        term = Term.objects.create(year=2019, term=1)
        session = Session.objects.create(term=term, session_number=1, date=date(2026, 10, 20), start_time=time(8), end_time=time(10))
        values = {'term': term, 'session': session, 'student_name': 'Student', 'student_id': 'id123',
                  'course_name': 'Accounting', 'course_code': 'acct101', 'room_code': 'R-1', 'department': 'Business'}
        first = Exam.objects.create(**values)
        duplicate = Exam.objects.create(**values)
        conflicting = Exam.objects.create(**{**values, 'department': 'Conflict'})
        try:
            with self.assertRaisesMessage(RuntimeError, 'Conflicting StudentExam'):
                executor = MigrationExecutor(connection)
                executor.migrate([('exams', '0007_exampdfupload_records_updated_and_more')])
            self.assertEqual(Exam.objects.count(), 3)
            self.assertEqual(Exam.objects.get(pk=first.pk).student_id, 'id123')
            Exam.objects.filter(pk=conflicting.pk).delete()
            executor = MigrationExecutor(connection)
            executor.migrate([('exams', '0007_exampdfupload_records_updated_and_more')])
            self.assertEqual(Exam.objects.count(), 1)
            self.assertEqual(Exam.objects.get().pk, first.pk)
            self.assertEqual(Exam.objects.get().student_id, 'ID123')
        finally:
            # Restore the current schema even if an assertion failed.
            if Exam.objects.filter(pk=conflicting.pk).exists():
                Exam.objects.filter(pk=conflicting.pk).delete()
            MigrationExecutor(connection).migrate([('exams', '0007_exampdfupload_records_updated_and_more')])


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentExamImportTests(TransactionTestCase):
    def test_competing_reimports_create_one_roster_row_and_session(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        term = ExamTerm.objects.create(year=2019, term=1)
        barrier = Barrier(2)

        def import_rows():
            try:
                barrier.wait(timeout=10)
                return write_student_rows(term, [student_row()])
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(import_rows) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, [(1, 0), (0, 0)])
        self.assertEqual(StudentExam.objects.count(), 1)
        self.assertEqual(ExamSession.objects.count(), 1)
