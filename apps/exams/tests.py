import shutil
import tempfile
from datetime import date, time, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.exams.models import (
    ExamNotificationLog,
    ExamPDFUpload,
    ExamScheduleEntry,
    ExamSession,
    ExamTerm,
    StudentExam,
)
from apps.exams.parsers.attendance_parser import _parse_attendance_text
from apps.exams.parsers.schedule_parser import _parse_schedule_text
from apps.exams.services import _ensure_active_term, _resolve_attendance_course_details


class ExamLookupApiTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(
            telegram_id=123456789,
            first_name='Exam',
            username='examuser',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_generate_jwt(self.student)}')

    def test_active_exam_term_returns_false_when_none_exists(self):
        response = self.client.get('/api/exams/active-term/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'active': False})

    def test_exam_endpoints_return_json_auth_error_without_token(self):
        self.client.credentials()

        active_response = self.client.get('/api/exams/active-term/')
        lookup_response = self.client.get('/api/exams/lookup/', {'name': 'azaria'})

        self.assertEqual(active_response.status_code, 403)
        self.assertEqual(active_response.data['detail'], 'Authentication required.')
        self.assertEqual(lookup_response.status_code, 403)
        self.assertEqual(lookup_response.data['detail'], 'Authentication required.')

    def test_exam_lookup_returns_active_term_results_in_session_order(self):
        active_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)
        inactive_term = ExamTerm.objects.create(year=2018, term=1, is_active=False)

        first_session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        second_session = ExamSession.objects.create(
            term=active_term,
            session_number=2,
            date=date(2026, 2, 21),
            start_time=time(10, 30),
            end_time=time(12, 30),
        )
        old_session = ExamSession.objects.create(
            term=inactive_term,
            session_number=1,
            date=date(2026, 1, 10),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )

        StudentExam.objects.create(
            term=active_term,
            session=second_session,
            student_name='Abirham Worku',
            student_id='93372',
            department='Accounting',
            course_name='Accounting Information System',
            course_code='ACFN 322',
            room_code='K-6',
        )
        StudentExam.objects.create(
            term=active_term,
            session=first_session,
            student_name='Abirham Worku',
            student_id='93372',
            department='Accounting',
            course_name='Taxation',
            course_code='ACFN 301',
            room_code='J-2',
        )
        StudentExam.objects.create(
            term=inactive_term,
            session=old_session,
            student_name='Abirham Worku',
            student_id='93372',
            department='Accounting',
            course_name='Old Course',
            course_code='OLD 101',
            room_code='Z-9',
        )

        response = self.client.get('/api/exams/lookup/', {'student_id': '93372'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['student_name'], 'Abirham Worku')
        self.assertEqual(response.data['student_id'], '93372')
        self.assertEqual(response.data['term'], '2018 Term 2 — Addis Ababa')
        self.assertEqual(len(response.data['exams']), 2)
        self.assertEqual(response.data['exams'][0]['course_code'], 'ACFN 301')
        self.assertEqual(response.data['exams'][1]['course_code'], 'ACFN 322')

    def test_exam_lookup_deduplicates_same_course_room_department_and_session(self):
        active_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)
        session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        exam_data = {
            'term': active_term,
            'session': session,
            'student_name': 'Abirham Worku',
            'student_id': '93372',
            'department': 'Accounting',
            'course_name': 'Taxation',
            'course_code': 'ACFN 301',
            'room_code': 'J-2',
        }
        StudentExam.objects.create(**exam_data)
        StudentExam.objects.create(**exam_data)

        response = self.client.get('/api/exams/lookup/', {'student_id': '93372'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['exams']), 1)
        self.assertEqual(response.data['exams'][0]['course_code'], 'ACFN 301')

    def test_exam_lookup_returns_partial_name_results(self):
        active_term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        first_session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        second_session = ExamSession.objects.create(
            term=active_term,
            session_number=3,
            date=date(2026, 2, 22),
            start_time=time(13, 30),
            end_time=time(15, 30),
        )

        StudentExam.objects.create(
            term=active_term,
            session=second_session,
            student_name='Azaria Wondwossen',
            student_id='95568',
            department='Economics',
            course_name='Global Trends',
            course_code='GLTR 1012',
            room_code='J-11',
        )
        StudentExam.objects.create(
            term=active_term,
            session=first_session,
            student_name='Azaria Wendwossen',
            student_id='95568',
            department='Economics',
            course_name='Entrepreneurship',
            course_code='MGMT 1012',
            room_code='J-23',
        )

        response = self.client.get('/api/exams/lookup/', {'name': 'azaria'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['student_id'], '95568')
        self.assertEqual(len(response.data['exams']), 2)
        self.assertEqual(response.data['exams'][0]['course_code'], 'MGMT 1012')
        self.assertEqual(response.data['exams'][1]['course_code'], 'GLTR 1012')

    def test_exam_lookup_uses_unified_query_param_for_student_id(self):
        active_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)
        session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        StudentExam.objects.create(
            term=active_term,
            session=session,
            student_name='Gedion Bekele',
            student_id='93372',
            department='Accounting',
            course_name='Taxation',
            course_code='ACFN 301',
            room_code='J-2',
        )

        response = self.client.get('/api/exams/lookup/', {'query': '93372'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['student_name'], 'Gedion Bekele')
        self.assertEqual(response.data['student_id'], '93372')

    def test_exam_lookup_name_search_matches_start_of_name_only(self):
        active_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)
        session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        StudentExam.objects.create(
            term=active_term,
            session=session,
            student_name='Gedion Bekele',
            student_id='93372',
            department='Accounting',
            course_name='Taxation',
            course_code='ACFN 301',
            room_code='J-2',
        )
        StudentExam.objects.create(
            term=active_term,
            session=session,
            student_name='Bekele Gedion Haile',
            student_id='93373',
            department='Accounting',
            course_name='Taxation',
            course_code='ACFN 301',
            room_code='J-3',
        )

        response = self.client.get('/api/exams/lookup/', {'query': 'Gedion'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['student_name'], 'Gedion Bekele')
        self.assertEqual(response.data['student_id'], '93372')

    def test_exam_lookup_rejects_short_name_queries(self):
        ExamTerm.objects.create(year=2018, term=2, is_active=True)

        response = self.client.get('/api/exams/lookup/', {'query': 'Ge'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Enter at least 3 characters to search by name')

    def test_exam_lookup_rejects_too_many_name_results(self):
        active_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)
        session = ExamSession.objects.create(
            term=active_term,
            session_number=1,
            date=date(2026, 2, 21),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        for index in range(21):
            StudentExam.objects.create(
                term=active_term,
                session=session,
                student_name=f'Gedion Student {index}',
                student_id=f'93{index:03d}',
                department='Accounting',
                course_name='Taxation',
                course_code=f'ACFN {index:03d}',
                room_code='J-2',
            )

        response = self.client.get('/api/exams/lookup/', {'query': 'Gedion'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Too many results for "Gedion"', response.data['error'])


class ExamTermModelTests(TestCase):
    def test_saving_new_active_term_deactivates_previous_active_term(self):
        first_term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        second_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)

        first_term.refresh_from_db()
        second_term.refresh_from_db()

        self.assertFalse(first_term.is_active)
        self.assertTrue(second_term.is_active)

    def test_activate_method_persists_active_term_and_deactivates_previous_one(self):
        first_term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        second_term = ExamTerm.objects.create(year=2018, term=2)

        second_term.activate()

        first_term.refresh_from_db()
        second_term.refresh_from_db()
        self.assertFalse(first_term.is_active)
        self.assertTrue(second_term.is_active)

    def test_deactivate_method_persists_without_reactivating_term(self):
        term = ExamTerm.objects.create(year=2018, term=1, is_active=True)

        term.deactivate()

        term.refresh_from_db()
        self.assertFalse(term.is_active)


@override_settings(ALLOWED_HOSTS=['testserver'])
class ExamTermAdminActivationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password',
        )
        self.client.force_login(self.user)

    def test_admin_activate_view_persists_new_active_term(self):
        first_term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        second_term = ExamTerm.objects.create(year=2018, term=2)

        response = self.client.post(
            f'/admin/exams/examterm/{second_term.pk}/activate/',
            HTTP_REFERER='/admin/exams/examterm/',
        )

        self.assertEqual(response.status_code, 302)
        first_term.refresh_from_db()
        second_term.refresh_from_db()
        self.assertFalse(first_term.is_active)
        self.assertTrue(second_term.is_active)

    def test_admin_deactivate_view_persists_inactive_term(self):
        term = ExamTerm.objects.create(year=2018, term=1, is_active=True)

        response = self.client.post(
            f'/admin/exams/examterm/{term.pk}/deactivate/',
            HTTP_REFERER='/admin/exams/examterm/',
        )

        self.assertEqual(response.status_code, 302)
        term.refresh_from_db()
        self.assertFalse(term.is_active)

    def test_admin_term_list_renders_activation_controls(self):
        ExamTerm.objects.create(year=2018, term=1, is_active=True)
        ExamTerm.objects.create(year=2018, term=2)

        response = self.client.get('/admin/exams/examterm/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Deactivate')
        self.assertContains(response, 'Activate')


class ExamPDFUploadQueueTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_admin_upload_queues_pdfs_without_processing_them_in_request(self):
        user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password',
        )
        self.client.force_login(user)

        with (
            patch('apps.exams.services.process_schedule_pdf') as process_schedule,
            patch('apps.exams.services.process_attendance_pdf') as process_attendance,
        ):
            response = self.client.post(
                '/admin/exams/examterm/upload-pdfs/',
                {
                    'schedule_pdf': SimpleUploadedFile(
                        'schedule.pdf',
                        b'%PDF schedule',
                        content_type='application/pdf',
                    ),
                    'attendance_pdfs': SimpleUploadedFile(
                        'attendance.pdf',
                        b'%PDF attendance',
                        content_type='application/pdf',
                    ),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/admin/exams/examterm/upload-pdfs/')
        process_schedule.assert_not_called()
        process_attendance.assert_not_called()

        uploads = list(ExamPDFUpload.objects.order_by('pdf_type'))
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(upload.status == ExamPDFUpload.STATUS_PENDING for upload in uploads))
        self.assertTrue(all(upload.content_hash for upload in uploads))

    def test_admin_upload_skips_duplicate_pdf_content(self):
        user = get_user_model().objects.create_superuser(
            username='dedupe-admin',
            email='dedupe-admin@example.com',
            password='password',
        )
        self.client.force_login(user)

        first_response = self.client.post(
            '/admin/exams/examterm/upload-pdfs/',
            {
                'schedule_pdf': SimpleUploadedFile(
                    'schedule.pdf',
                    b'%PDF same schedule',
                    content_type='application/pdf',
                ),
            },
        )
        second_response = self.client.post(
            '/admin/exams/examterm/upload-pdfs/',
            {
                'schedule_pdf': SimpleUploadedFile(
                    'schedule-copy.pdf',
                    b'%PDF same schedule',
                    content_type='application/pdf',
                ),
            },
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(ExamPDFUpload.objects.count(), 1)
        self.assertEqual(ExamPDFUpload.objects.get().original_name, 'schedule.pdf')

    def test_process_exam_pdfs_command_processes_pending_uploads(self):
        upload = ExamPDFUpload.objects.create(
            original_name='schedule.pdf',
            pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
        )
        upload.file.save(
            'schedule.pdf',
            SimpleUploadedFile('schedule.pdf', b'%PDF schedule', content_type='application/pdf'),
            save=True,
        )

        def process_schedule(upload_record):
            self.assertEqual(upload_record.status, ExamPDFUpload.STATUS_PROCESSING)
            upload_record.status = ExamPDFUpload.STATUS_PROCESSED
            upload_record.records_created = 7
            upload_record.error_message = ''
            upload_record.save(update_fields=['status', 'records_created', 'error_message'])
            return True, 7, ''

        stdout = StringIO()
        with patch('apps.exams.services.process_schedule_pdf', side_effect=process_schedule):
            call_command('process_exam_pdfs', stdout=stdout)

        upload.refresh_from_db()
        self.assertEqual(upload.status, ExamPDFUpload.STATUS_PROCESSED)
        self.assertEqual(upload.records_created, 7)
        self.assertIn('Processed=1', stdout.getvalue())

    def test_admin_process_action_starts_background_thread(self):
        user = get_user_model().objects.create_superuser(
            username='processor',
            email='processor@example.com',
            password='password',
        )
        self.client.force_login(user)
        ExamPDFUpload.objects.create(
            original_name='pending.pdf',
            pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
            status=ExamPDFUpload.STATUS_PENDING,
        )

        with patch('apps.exams.admin.threading.Thread') as thread_class:
            response = self.client.post(
                '/admin/exams/examterm/upload-pdfs/',
                {'action': 'process'},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/admin/exams/examterm/upload-pdfs/')
        thread_class.assert_called_once()
        self.assertEqual(thread_class.call_args.kwargs['daemon'], True)
        self.assertEqual(
            thread_class.call_args.kwargs['target'].__name__,
            '_process_exam_pdfs_in_background',
        )
        thread_class.return_value.start.assert_called_once()

    def test_admin_upload_status_returns_term_counts(self):
        user = get_user_model().objects.create_superuser(
            username='status-admin',
            email='status-admin@example.com',
            password='password',
        )
        self.client.force_login(user)
        term = ExamTerm.objects.create(year=2018, term=1)
        other_term = ExamTerm.objects.create(year=2018, term=2)
        ExamPDFUpload.objects.create(
            term=term,
            original_name='pending.pdf',
            pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
            status=ExamPDFUpload.STATUS_PENDING,
        )
        ExamPDFUpload.objects.create(
            term=term,
            original_name='processing.pdf',
            pdf_type=ExamPDFUpload.TYPE_ATTENDANCE,
            status=ExamPDFUpload.STATUS_PROCESSING,
        )
        ExamPDFUpload.objects.create(
            term=term,
            original_name='processed.pdf',
            pdf_type=ExamPDFUpload.TYPE_ATTENDANCE,
            status=ExamPDFUpload.STATUS_PROCESSED,
        )
        ExamPDFUpload.objects.create(
            term=term,
            original_name='failed.pdf',
            pdf_type=ExamPDFUpload.TYPE_ATTENDANCE,
            status=ExamPDFUpload.STATUS_FAILED,
        )
        ExamPDFUpload.objects.create(
            term=other_term,
            original_name='other.pdf',
            pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
            status=ExamPDFUpload.STATUS_PENDING,
        )

        response = self.client.get(f'/admin/exams/examterm/{term.id}/upload-status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'pending': 1, 'processing': 1, 'processed': 1, 'failed': 1},
        )


class ScheduleParserTests(TestCase):
    def test_parse_schedule_text_extracts_term_sessions_and_rooms(self):
        text = """
Final Examination Schedule (2018 - First Term)
Faculty of Distance Education
Center: Addis Ababa
Date: Saturday, February 21, 2026
Exam Time: 8:00 A.M - 10:00 A.M
Exam Session: I

1 Accounting Information System ACFN 322 30 10 K-1 K-2 K-3
2 Taxation ACFN 301 20 10 J-1 J-2
"""

        parsed = _parse_schedule_text(text, [text])

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2018)
        self.assertEqual(parsed.term, 1)
        self.assertEqual(parsed.center, 'Addis Ababa')
        self.assertEqual(parsed.earliest_date, date(2026, 2, 21))
        self.assertEqual(len(parsed.sessions), 1)
        self.assertEqual(parsed.sessions[0].entries[0].course_code, 'ACFN 322')
        self.assertEqual(parsed.sessions[0].entries[0].rooms, ['K-1', 'K-2', 'K-3'])

    def test_parse_schedule_text_handles_multiline_course_rows(self):
        text = """
Final Examination Schedule (2018 - First Term)
Faculty of Distance Education
Center: Addis Ababa
Date: Sunday, February 22, 2026
Exam Session: I
Exam Time: 8:00 A.M - 10:00 A.M
SN COURSE NAMES COURSE CODES Exam Room/s
1 Physical Distribution and Channel Management MRKT 413 36 19 20 J-20 J-22
2 Computer Application in Economics ECON 263 3
Advanced/Strategic Entrepreneurship and Enterprise MGMT 424
3 62 31 31 J-13 J-18
Development/Small Business Mgmt.
4 Critical Thinking/Logic LOCT 1011 124 31 31 31 K-4 K-3 K-2
31 K-1
Advanced Accounting - I/Advanced Financial
5 ACCT 401 15
Accounting - I
26 J-7
Advanced Accounting - II/Advanced Financial ACFN 402
6 5
Accounting - II
10 Development Economics (For Management Only) ECON 365 47 23 24 J-25 J-26
"""

        parsed = _parse_schedule_text(text, [text])

        self.assertIsNotNone(parsed)
        entries = {entry.course_code: entry for entry in parsed.sessions[0].entries}
        self.assertEqual(entries['MGMT 424'].rooms, ['J-13', 'J-18'])
        self.assertEqual(entries['LOCT 1011'].rooms, ['K-4', 'K-3', 'K-2', 'K-1'])
        self.assertEqual(entries['ACCT 401'].rooms, ['J-7'])
        self.assertEqual(entries['ACFN 402'].total_students, 5)
        self.assertEqual(entries['ECON 365'].rooms, ['J-25', 'J-26'])


class AttendanceParserTests(TestCase):
    def test_parse_attendance_text_extracts_header_and_students(self):
        text = """
Unity University
(2018 I Term)
Exam Date: February 21, 2026
Session: II: 10:30 AM - 12:30 PM
(ADDIS ABABA CENTER) Number of Examinees: 2
(ATTENDANCE SHEET) EXAM ROOM: K-6
LIST OF EXAMINEES FOR "Accounting Information System" (ACFN 322)

1 Abirham Worku 93372 M Accounting
2 Meron Bekele 93373 F Accounting
"""

        parsed_blocks = _parse_attendance_text(text)
        parsed = parsed_blocks[0]

        self.assertEqual(len(parsed_blocks), 1)
        self.assertEqual(parsed.year, 2018)
        self.assertEqual(parsed.term, 1)
        self.assertEqual(parsed.session_num, 2)
        self.assertEqual(parsed.room_code, 'K-6')
        self.assertEqual(parsed.course_code, 'ACFN 322')
        self.assertEqual(len(parsed.students), 2)
        self.assertEqual(parsed.students[0].student_id, '93372')

    def test_parse_attendance_text_supports_smart_quotes_mixed_case_codes_and_multiple_blocks(self):
        text = """
Unity University
(2018 I Term)
Exam Date: February 22, 2026
FACULTY OF DISTANCE EDUCATION Session: II: 10:30 AM – 12:30 PM
(ADDIS ABABA CENTER) Number of Examinees: 2
(ATTENDANCE SHEET) EXAM ROOM: J-25
LIST OF EXAMINEES FOR “Administrative and Business Communication” ( Mgmt 212)
SN Name of Examinees ID. Sex Department Signature Phone Number Remark
1 Abeba Habte 95708 F Management
2 Amanuel Getachew * M Management

Unity University
(2018 I Term)
Exam Date: February 22, 2026
FACULTY OF DISTANCE EDUCATION Session: II: 10:30 AM – 12:30 PM
(ADDIS ABABA CENTER) Number of Examinees: 2
(ATTENDANCE SHEET) EXAM ROOM: J-26
LIST OF EXAMINEES FOR “Administrative and Business Communication” ( Mgmt 212)
SN Name of Examinees ID. Sex Department Signature Phone Number Remark
1 Sarah Noah Ali 95886 F Management
2 Siket Bezu 95803 F Management
"""

        parsed_blocks = _parse_attendance_text(text)

        self.assertEqual(len(parsed_blocks), 2)
        self.assertEqual(parsed_blocks[0].course_code, 'MGMT 212')
        self.assertEqual(parsed_blocks[0].room_code, 'J-25')
        self.assertEqual(parsed_blocks[0].students[1].student_id, '')
        self.assertEqual(parsed_blocks[1].room_code, 'J-26')
        self.assertEqual(len(parsed_blocks[1].students), 2)

    def test_parse_attendance_text_handles_blank_course_code_and_wrapped_names(self):
        text = """
Unity University
(201 8 I Term)
Exam Date: February 22, 2026
FACULTY OF DISTANCE EDUCATION Session: I: 8:00 AM - 10:00 AM
(ADDIS ABABA CENTER) Number of Examinees: 31
(ATTENDANCE SHEET) EXAM ROOM: K-4
LIST OF EXAMINEES FOR Critical Thinking " ( LoCT 1011)
SN Name of Examinees ID Sex Department Signature Phone Number Remark
1 Abduljelil Aman Bunki 96117 M Management
8 Amanuel Temesgen 95928 F Management
Alemneh
10 Arsema Yishak 96011 F Marketing
Abrhame
15 Bereket B/meskel * M Management
Mekonen
Attendance of Students with valid cases
"""

        parsed_blocks = _parse_attendance_text(text)

        self.assertEqual(len(parsed_blocks), 1)
        self.assertEqual(parsed_blocks[0].year, 2018)
        self.assertEqual(parsed_blocks[0].course_code, 'LOCT 1011')
        self.assertEqual(parsed_blocks[0].students[1].name, 'Amanuel Temesgen Alemneh')
        self.assertEqual(parsed_blocks[0].students[2].name, 'Arsema Yishak Abrhame')
        self.assertEqual(parsed_blocks[0].students[3].student_id, '')

    def test_parse_attendance_text_handles_room_spacing_compact_dates_and_rows_without_serial_prefix(self):
        text = """
Unity University
(2018 I Term)
Exam Date: February 21,2026
FACULTY OF DISTANCE EDUCATION Session: IV: 3:30 PM - 5:30 PM
(ADDIS ABABA CENTER) Number of Examinees: 03
(ATTENDANCE SHEET) EXAM ROOM: J -8
LIST OF EXAMINEES FOR Development Economics I " (Econ 371)
SN Name of Examinees ID Sex Department Signature Phone Number Remark
1 Adoniyas Bekele 94711 M Economics
Eyuel Shimelis 92163 M Economics
3 Saron Abera 90887 F Economics
Attendance of Students with valid cases
"""

        parsed_blocks = _parse_attendance_text(text)

        self.assertEqual(len(parsed_blocks), 1)
        self.assertEqual(parsed_blocks[0].exam_date, date(2026, 2, 21))
        self.assertEqual(parsed_blocks[0].room_code, 'J-8')
        self.assertEqual(parsed_blocks[0].course_code, 'ECON 371')
        self.assertEqual(len(parsed_blocks[0].students), 3)
        self.assertEqual(parsed_blocks[0].students[1].name, 'Eyuel Shimelis')


class AttendanceCourseResolutionTests(TestCase):
    def test_resolve_attendance_course_details_uses_schedule_entries_when_header_code_is_blank(self):
        term = ExamTerm.objects.create(year=2018, term=1)
        session = ExamSession.objects.create(
            term=term,
            session_number=1,
            date=date(2026, 2, 22),
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        ExamScheduleEntry.objects.create(
            session=session,
            course_name='Advanced Accounting - I/Advanced Financial Accounting - I',
            course_code='ACCT 401',
            total_students=15,
            rooms='J-7',
        )
        ExamScheduleEntry.objects.create(
            session=session,
            course_name='Advanced Accounting - II/Advanced Financial Accounting - II',
            course_code='ACFN 402',
            total_students=5,
            rooms='J-8',
        )

        parsed = SimpleNamespace(
            course_name='Advanced Acconting I/ Adv. Finan. Acct I',
            course_code='',
            room_code='J-7',
        )

        resolved_name, resolved_code = _resolve_attendance_course_details(
            term=term,
            session=session,
            parsed=parsed,
            original_name='Advanced Accounting I ( Adv. Fina. Acct I).pdf',
        )

        self.assertEqual(resolved_name, 'Advanced Accounting - I/Advanced Financial Accounting - I')
        self.assertEqual(resolved_code, 'ACCT 401')

        parsed.course_name = 'Advanced Acconting II ( Adv. Fin. Acct. II)'
        parsed.room_code = 'J-7'

        resolved_name, resolved_code = _resolve_attendance_course_details(
            term=term,
            session=session,
            parsed=parsed,
            original_name='Advanced Accounting II ( Adv. Fin. Acct. II).pdf',
        )

        self.assertEqual(resolved_name, 'Advanced Accounting - II/Advanced Financial Accounting - II')
        self.assertEqual(resolved_code, 'ACFN 402')


class ExamTermActivationTests(TestCase):
    def test_ensure_active_term_activates_imported_term_when_none_exists(self):
        term = ExamTerm.objects.create(year=2018, term=1, center='Addis Ababa')

        _ensure_active_term(term)

        term.refresh_from_db()
        self.assertTrue(term.is_active)

    def test_ensure_active_term_does_not_override_existing_active_term(self):
        active_term = ExamTerm.objects.create(year=2018, term=1, center='Addis Ababa', is_active=True)
        imported_term = ExamTerm.objects.create(year=2018, term=2, center='Addis Ababa')

        _ensure_active_term(imported_term)

        active_term.refresh_from_db()
        imported_term.refresh_from_db()
        self.assertTrue(active_term.is_active)
        self.assertFalse(imported_term.is_active)


@override_settings(TELEGRAM_BOT_TOKEN='test-token')
class ExamNotificationCommandTests(TestCase):
    @patch('telegram.Bot.send_message', new_callable=AsyncMock)
    def test_send_exam_notifications_targets_only_active_students_once(self, mock_send_message):
        term = ExamTerm.objects.create(
            year=2018,
            term=1,
            is_active=True,
            exam_start_date=timezone.now().date() + timedelta(days=7),
        )
        Student.objects.create(telegram_id=1, first_name='Active One', is_active=True)
        Student.objects.create(telegram_id=2, first_name='Active Two', is_active=True)
        Student.objects.create(telegram_id=3, first_name='Inactive', is_active=False)
        out = StringIO()

        call_command('send_exam_notifications', stdout=out)

        self.assertEqual(mock_send_message.await_count, 2)
        log = ExamNotificationLog.objects.get(term=term, days_before=7)
        self.assertEqual(log.sent_count, 2)
        self.assertEqual(log.failed_count, 0)
        self.assertIn('Sent 7-day notification: 2 delivered, 0 failed', out.getvalue())

        call_command('send_exam_notifications', stdout=out)
        self.assertEqual(mock_send_message.await_count, 2)
        self.assertEqual(ExamNotificationLog.objects.filter(term=term, days_before=7).count(), 1)
