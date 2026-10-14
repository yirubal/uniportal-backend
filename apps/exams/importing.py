"""Validated, transactional schedule and attendance writes."""
import re
from datetime import date, time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import ExamSession, ExamTerm, StudentExam

STUDENT_FIELDS = ('student_name', 'student_id', 'department', 'course_name', 'course_code', 'room_code')


def normalize_course_code(value):
    compact = re.sub(r'\s+', '', value or '')
    match = re.match(r'([A-Za-z]+)(\d{3,4}[A-Za-z]?)$', compact)
    return f'{match[1].upper()} {match[2].upper()}' if match else (value or '').strip().upper()


def validate_term(year, term, center):
    if not isinstance(year, int) or not 1 <= year <= 9999 or term not in {1, 2, 3}:
        raise ValueError('Invalid exam year/term.')
    if not isinstance(center, str) or not 1 <= len(center.strip()) <= 100:
        raise ValueError('Invalid exam center.')


def validate_session(number, exam_date, start, end):
    if not isinstance(number, int) or not 1 <= number <= 100:
        raise ValueError('Session number must be 1–100.')
    if not isinstance(exam_date, date) or not isinstance(start, time) or not isinstance(end, time):
        raise ValueError('Invalid session date/time.')
    if start.tzinfo or end.tzinfo or start >= end:
        raise ValueError('Session start must precede end, using local times.')
    return {'session_number': number, 'date': exam_date, 'start_time': start, 'end_time': end}


def session_specs(rows):
    specs = {}
    for row in rows:
        spec = validate_session(row['session_number'], row['date'], row['start_time'], row['end_time'])
        key = (spec['session_number'], spec['date'])
        if key in specs and specs[key] != spec:
            raise ValueError('Conflicting session times within the import.')
        specs[key] = spec
    if not specs or len(specs) > 200:
        raise ValueError('Import must contain 1–200 distinct sessions.')
    return specs


def validate_student_rows(rows):
    if not rows or len(rows) > settings.MAX_EXAM_IMPORT_ROWS:
        raise ValueError(f'Import must contain 1–{settings.MAX_EXAM_IMPORT_ROWS} student rows.')
    cleaned = {}
    for row in rows:
        data = dict(row)
        for field in STUDENT_FIELDS:
            value = data.get(field, '')
            if not isinstance(value, str):
                raise ValueError(f'Invalid {field}.')
            value = value.strip()
            if field == 'student_id':
                value = value.upper()
            if field == 'course_code':
                value = normalize_course_code(value)
            try:
                data[field] = StudentExam._meta.get_field(field).clean(value, None)
            except ValidationError as exc:
                raise ValueError(f'{field}: {"; ".join(exc.messages)}') from exc
        key = (data['session_number'], data['date'], data['course_code'], data['room_code'],
               'id' if data['student_id'] else 'name', data['student_id'] or data['student_name'])
        if key in cleaned and cleaned[key] != data:
            raise ValueError('Conflicting student details for the same exam within the import.')
        cleaned[key] = data
    result = list(cleaned.values())
    session_specs(result)
    return result


def get_sessions(term, specs):
    """Caller owns the term lock; reject time changes pending explicit correction."""
    condition = Q()
    for number, exam_date in specs:
        condition |= Q(session_number=number, date=exam_date)
    sessions = {(row.session_number, row.date): row for row in ExamSession.objects.filter(term=term).filter(condition)}
    for key, row in sessions.items():
        spec = specs[key]
        if (row.start_time, row.end_time) != (spec['start_time'], spec['end_time']):
            raise ValueError(f'Session {row.session_number} on {row.date} has conflicting times; correct the session explicitly before importing.')
    missing = [ExamSession(term=term, **spec) for key, spec in specs.items() if key not in sessions]
    if missing:
        ExamSession.objects.bulk_create(missing, batch_size=100)
        sessions = {(row.session_number, row.date): row for row in ExamSession.objects.filter(term=term).filter(condition)}
    return sessions


def student_identity(row):
    return (row.session_id, row.course_code, row.room_code, 'id' if row.student_id else 'name', row.student_id or row.student_name)


@transaction.atomic
def write_student_rows(term, rows):
    rows = validate_student_rows(rows)
    ExamTerm.objects.select_for_update().get(pk=term.pk)
    sessions = get_sessions(term, session_specs(rows))
    created, updated = 0, 0
    # Fetch/update exact natural keys in batches. Never load an entire term roster.
    for offset in range(0, len(rows), 100):
        batch = rows[offset:offset + 100]
        desired = []
        condition = Q()
        for row in batch:
            item = StudentExam(term=term, session=sessions[(row['session_number'], row['date'])],
                               **{field: row[field] for field in STUDENT_FIELDS})
            desired.append(item)
            identity = {'session_id': item.session_id, 'course_code': item.course_code, 'room_code': item.room_code,
                        'student_id': item.student_id}
            if not item.student_id:
                identity['student_name'] = item.student_name
            condition |= Q(**identity)
        existing = {student_identity(row): row for row in StudentExam.objects.filter(term=term).filter(condition)}
        inserts, updates = [], []
        for item in desired:
            previous = existing.get(student_identity(item))
            if previous is None:
                inserts.append(item)
            elif any(getattr(previous, field) != getattr(item, field) for field in STUDENT_FIELDS):
                for field in STUDENT_FIELDS:
                    setattr(previous, field, getattr(item, field))
                updates.append(previous)
        StudentExam.objects.bulk_create(inserts, batch_size=100)
        StudentExam.objects.bulk_update(updates, STUDENT_FIELDS, batch_size=100)
        created += len(inserts)
        updated += len(updates)
    return created, updated
