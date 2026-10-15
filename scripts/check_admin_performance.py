"""Synthetic rendered-admin benchmark using a fresh in-memory SQLite database.

Run: venv/bin/python scripts/check_admin_performance.py > report.json
Never reads .env or uses a configured application/production database.
"""
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def seed_rows(start, stop, actor):
    from django.utils import timezone
    from apps.accounts.models import BroadcastMessage, Student, SubscriptionPlan, SubscriptionRequest
    from apps.bot.models import NotificationDelivery
    from apps.content.models import Course, CoursePlacement, Department, Resource
    from apps.exams.models import ExamPDFUpload, ExamSession, ExamTerm, StudentExam
    from apps.quiz.models import Chapter, ExamPaper, Question
    department, _ = Department.objects.get_or_create(name='Sample department')
    plan, _ = SubscriptionPlan.objects.get_or_create(plan_id='semester', defaults={'name': 'Sample plan', 'price': 100, 'days': 30})
    broadcast = BroadcastMessage.objects.first() or BroadcastMessage.objects.create(message='Sample broadcast', sent_by=actor)
    for i in range(start, stop):
        course = Course.objects.create(name=f'Sample course {i:03}', code=f'S{i:03}')
        CoursePlacement.objects.create(course=course, department=department, program='distance', year=1, period=1)
        student = Student.objects.create(telegram_id=900000 + i, first_name=f'Sample {i}', preferred_department=department)
        SubscriptionRequest.objects.create(student=student, plan=plan, reference=f'BENCH-{i}', amount=100,
                                           status='approved', activated_by=actor)
        term = ExamTerm.objects.create(year=2018, term=1, center=f'Sample center {i}', is_active=i == 0)
        session = ExamSession.objects.create(term=term, session_number=1, date='2026-11-01', start_time='09:00', end_time='11:00')
        StudentExam.objects.create(term=term, session=session, student_name=f'Sample {i}', student_id=str(i),
                                   course_name=course.name, course_code=course.code, room_code='R1')
        ExamPDFUpload.objects.create(original_name=f'Sample {i}.pdf', pdf_type='schedule', term=term)
        paper = ExamPaper.objects.create(title=f'Sample paper {i}', course=course, exam_type='final', year=2018)
        chapter = Chapter.objects.create(title=f'Sample chapter {i}', course=course, number=1)
        Question.objects.create(text=f'Sample question {i}', exam_paper=paper, chapter=chapter)
        resource = Resource(title=f'Sample resource {i}', file='sample.pdf', file_type='module')
        Resource.objects.bulk_create([resource])
        resource.courses.add(course)
        NotificationDelivery.objects.create(deduplication_key=f'sample:{i}', chat_id=student.telegram_id,
                                            text='Sample delivery', broadcast=broadcast)


PAGES = {
    'overview': '/admin/', 'exam_terms': '/admin/exams/examterm/',
    'papers': '/admin/quiz/exampaper/', 'chapters': '/admin/quiz/chapter/',
    'questions': '/admin/quiz/question/', 'students': '/admin/accounts/student/',
    'payments': '/admin/accounts/subscriptionrequest/', 'deliveries': '/admin/bot/notificationdelivery/',
}


def measure(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    result = {}
    for name, path in PAGES.items():
        assert client.get(path).status_code == 200, path  # warm template and permission caches
        samples, counts = [], []
        for _ in range(3):
            started = time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response = client.get(path)
            assert response.status_code == 200, path
            samples.append((time.perf_counter() - started) * 1000)
            counts.append(len(queries))
        result[name] = {'queries': max(counts), 'median_ms': round(statistics.median(samples), 2)}
    return result


def initialize():
    # Explicitly override inherited settings before Django starts.
    os.environ['READ_DOT_ENV'] = 'false'
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    import django
    django.setup()
    logging.disable(logging.CRITICAL)
    from django.conf import settings
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.test import Client
    settings.ALLOWED_HOSTS = ['testserver', '127.0.0.1']
    call_command('migrate', verbosity=0)
    actor = get_user_model().objects.create_superuser('sample-admin')
    client = Client()
    client.force_login(actor)
    return actor, client


if __name__ == '__main__':
    actor, client = initialize()
    seed_rows(0, 1, actor)
    one = measure(client)
    seed_rows(1, 25, actor)
    print(json.dumps({'database': 'isolated in-memory SQLite', 'method': 'warm rendered GETs; median of 3; queries include session/admin overhead',
                      'one_row': one, 'twenty_five_rows': measure(client)}, indent=2))
