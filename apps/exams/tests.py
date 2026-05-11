from datetime import date, time

from rest_framework.test import APITestCase

from apps.accounts.models import Student
from apps.api.views import _generate_jwt
from apps.exams.models import ExamSession, ExamTerm, StudentExam


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


class ExamTermModelTests(APITestCase):
    def test_saving_new_active_term_deactivates_previous_active_term(self):
        first_term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        second_term = ExamTerm.objects.create(year=2018, term=2, is_active=True)

        first_term.refresh_from_db()
        second_term.refresh_from_db()

        self.assertFalse(first_term.is_active)
        self.assertTrue(second_term.is_active)
