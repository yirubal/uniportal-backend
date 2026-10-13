import logging
import os
import re
import tempfile
from difflib import SequenceMatcher
from django.db import transaction
from django.db.models import Min
from .importing import (normalize_course_code as _normalize_course_code, validate_term,
                        validate_session, validate_student_rows, write_student_rows, get_sessions)

logger = logging.getLogger(__name__)


def process_schedule_pdf(upload_record):
    """
    Processes the schedule PDF (Type 1).
    Extracts sessions, exam dates, and course schedule entries.
    Also sets exam_start_date on the ExamTerm.
    """
    from .models import ExamScheduleEntry, ExamSession, ExamTerm
    from .parsers.schedule_parser import parse_schedule_pdf

    suffix = os.path.splitext(upload_record.original_name)[1]
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            upload_record.file.open('rb')
            for chunk in upload_record.file.chunks():
                tmp.write(chunk)
        upload_record.file.close()

        parsed = parse_schedule_pdf(tmp_path)
        if not parsed:
            raise ValueError('Parser returned no data — check PDF format')

        from .importing import session_specs
        from django.core.exceptions import ValidationError
        from django.conf import settings
        validate_term(parsed.year, parsed.term, parsed.center or 'Addis Ababa')
        specs = []
        entries = {}
        for parsed_session in parsed.sessions:
            spec = validate_session(parsed_session.session_number, parsed_session.date,
                                    parsed_session.start_time, parsed_session.end_time)
            specs.append(spec)
            if not parsed_session.entries:
                raise ValueError('Session has no schedule entries.')
            for entry in parsed_session.entries:
                code = _normalize_course_code(entry.course_code)
                values = {'course_name': entry.course_name.strip(), 'course_code': code,
                          'total_students': entry.total_students, 'rooms': ', '.join(entry.rooms)}
                try:
                    for field, value in values.items():
                        ExamScheduleEntry._meta.get_field(field).clean(value, None)
                except ValidationError as exc:
                    raise ValueError('; '.join(exc.messages)) from exc
                if not 0 <= entry.total_students <= 2147483647:
                    raise ValueError('Invalid schedule student count.')
                key = (spec['session_number'], spec['date'], code)
                if key in entries and entries[key] != values:
                    raise ValueError('Conflicting course entries within the schedule.')
                entries[key] = values
                if len(entries) > settings.MAX_EXAM_IMPORT_ROWS:
                    raise ValueError('Schedule import row limit exceeded.')
        validated_sessions = session_specs(specs)
        if not entries:
            raise ValueError('Schedule contains no courses.')
        if upload_record.term_id and (upload_record.term.year, upload_record.term.term, upload_record.term.center) != (
                parsed.year, parsed.term, parsed.center or 'Addis Ababa'):
            raise ValueError('Uploaded schedule does not match its selected term.')
        with transaction.atomic():
            term, _ = ExamTerm.objects.get_or_create(year=parsed.year, term=parsed.term, center=parsed.center or 'Addis Ababa')
            ExamTerm.objects.select_for_update().get(pk=term.pk)
            _ensure_active_term(term)
            sessions = get_sessions(term, validated_sessions)
            wanted_sessions = [row.pk for row in sessions.values()]
            existing = {(row.session_id, row.course_code): row for row in ExamScheduleEntry.objects.filter(session_id__in=wanted_sessions)}
            inserts, updates = [], []
            for (number, exam_date, code), values in entries.items():
                session = sessions[(number, exam_date)]
                previous = existing.get((session.pk, code))
                if previous is None:
                    inserts.append(ExamScheduleEntry(session=session, **values))
                elif any(getattr(previous, field) != value for field, value in values.items()):
                    for field, value in values.items():
                        setattr(previous, field, value)
                    updates.append(previous)
            ExamScheduleEntry.objects.bulk_create(inserts, batch_size=100)
            ExamScheduleEntry.objects.bulk_update(updates, ['course_name', 'rooms', 'total_students'], batch_size=100)
            created = len(inserts)
            if parsed.earliest_date:
                term.exam_start_date = ExamSession.objects.filter(term=term).aggregate(first=Min('date'))['first']
                term.save(update_fields=['exam_start_date'])
            upload_record.term = term
            upload_record.status = upload_record.STATUS_PROCESSED
            upload_record.records_created = created
            upload_record.records_updated = len(updates)
            upload_record.error_message = ''
            upload_record.save(update_fields=['term', 'status', 'records_created', 'records_updated', 'error_message'])

        logger.info('Schedule PDF processed: %s schedule entries created', created)
        return True, created, ''

    except Exception as exc:
        error = str(exc)
        logger.error('Schedule PDF processing failed: %s', error)
        upload_record.status = upload_record.STATUS_FAILED
        upload_record.error_message = error
        upload_record.save(update_fields=['status', 'error_message'])
        return False, 0, error

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def process_attendance_pdf(upload_record):
    """
    Processes an attendance sheet PDF (Type 2).
    Extracts student name, ID, room, course, session data.
    """
    from .models import ExamSession, ExamTerm, StudentExam
    from .parsers.attendance_parser import parse_attendance_pdf

    suffix = os.path.splitext(upload_record.original_name)[1]
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            upload_record.file.open('rb')
            for chunk in upload_record.file.chunks():
                tmp.write(chunk)
        upload_record.file.close()

        parsed_blocks = parse_attendance_pdf(tmp_path)
        if not parsed_blocks:
            raise ValueError('Parser returned no data — check PDF format')

        first_block = parsed_blocks[0]
        center = upload_record.term.center if upload_record.term_id else 'Addis Ababa'
        validate_term(first_block.year, first_block.term, center)
        if any((block.year, block.term) != (first_block.year, first_block.term) for block in parsed_blocks):
            raise ValueError('Attendance blocks refer to different terms.')
        if upload_record.term_id and (upload_record.term.year, upload_record.term.term) != (first_block.year, first_block.term):
            raise ValueError('Attendance PDF does not match its selected term.')
        # Resolve read-only catalogue/schedule hints before creating any rows.
        known_term = ExamTerm.objects.filter(year=first_block.year, term=first_block.term, center=center).first()
        context_term = known_term or ExamTerm(year=first_block.year, term=first_block.term, center=center)
        rows = []
        for block in parsed_blocks:
            if not block.students:
                raise ValueError('Attendance block has no students.')
            spec = validate_session(block.session_num, block.exam_date, block.start_time, block.end_time)
            context_session = ExamSession(term=context_term, **spec)
            name, code = _resolve_attendance_course_details(context_term, context_session, block, upload_record.original_name)
            for student in block.students:
                rows.append({**spec, 'student_name': student.name, 'student_id': student.student_id,
                             'department': student.department, 'course_name': name,
                             'course_code': code, 'room_code': block.room_code})
        rows = validate_student_rows(rows)
        with transaction.atomic():
            term, _ = ExamTerm.objects.get_or_create(year=first_block.year, term=first_block.term, center=center)
            ExamTerm.objects.select_for_update().get(pk=term.pk)
            _ensure_active_term(term)
            created, updated = write_student_rows(term, rows)
            upload_record.term = term
            upload_record.status = upload_record.STATUS_PROCESSED
            upload_record.records_created = created
            upload_record.records_updated = updated
            upload_record.error_message = ''
            upload_record.save(update_fields=['term', 'status', 'records_created', 'records_updated', 'error_message'])
        logger.info('Attendance PDF processed: %s created, %s updated', created, updated)
        return True, created, ''

    except Exception as exc:
        error = str(exc)
        logger.error('Attendance PDF failed: %s', error)
        upload_record.status = upload_record.STATUS_FAILED
        upload_record.error_message = error
        upload_record.save(update_fields=['status', 'error_message'])
        return False, 0, error

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _resolve_attendance_course_details(term, session, parsed, original_name):
    from apps.content.models import Course
    from .models import ExamScheduleEntry

    course_name = (parsed.course_name or '').strip()
    course_code = _normalize_course_code(parsed.course_code)
    filename_hint = _course_hint_from_filename(original_name)

    if course_name and course_code:
        return course_name, course_code

    schedule_candidates = (
        ExamScheduleEntry.objects.filter(
            session__term_id=term.pk,
            session__date=session.date,
            session__session_number=session.session_number,
        )
        .select_related('session')
    )
    resolved = _pick_best_schedule_match(
        schedule_candidates,
        room_code=parsed.room_code,
        course_name=course_name,
        filename_hint=filename_hint,
    )
    if resolved:
        resolved_name, resolved_code = resolved
        return resolved_name, resolved_code

    if course_name:
        resolved = _pick_best_catalog_match(Course.objects.all(), course_name, filename_hint)
        if resolved:
            return resolved

    if not course_name and filename_hint:
        course_name = filename_hint

    return course_name, course_code


def _ensure_active_term(term):
    from .models import ExamTerm

    if term.is_active or ExamTerm.objects.filter(is_active=True).exists():
        return

    term.is_active = True
    term.save(update_fields=['is_active'])


def dedupe_student_exam_rows(exams):
    """
    Keep one row for duplicate imported exam entries while preserving order.
    Duplicates are scoped to the same student, session, course, department, and room.
    """
    seen = set()
    unique = []
    for exam in exams:
        key = (
            exam.student_id.strip().lower(),
            exam.student_name.strip().lower(),
            exam.department.strip().lower(),
            exam.course_name.strip().lower(),
            exam.course_code.strip().lower(),
            exam.room_code.strip().lower(),
            exam.session_id,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(exam)
    return unique


def _pick_best_schedule_match(candidates, room_code, course_name, filename_hint):
    best_score = 0.0
    best_match = None
    reference_names = [value for value in [course_name, filename_hint] if value]
    expected_level = _extract_course_level(course_name) or _extract_course_level(filename_hint)

    for entry in candidates:
        score = 0.0
        rooms = [room.strip() for room in (entry.rooms or '').split(',') if room.strip()]
        if room_code and room_code in rooms:
            score += 0.45

        for reference in reference_names:
            score += 0.55 * _course_similarity(reference, entry.course_name)

        candidate_level = _extract_course_level(entry.course_name)
        if expected_level and candidate_level:
            if expected_level == candidate_level:
                score += 0.35
            else:
                score -= 0.6

        if score > best_score:
            best_score = score
            best_match = entry

    if best_match and best_score >= 0.55:
        return best_match.course_name, _normalize_course_code(best_match.course_code)
    return None


def _pick_best_catalog_match(candidates, course_name, filename_hint):
    best_score = 0.0
    best_match = None
    reference_names = [value for value in [course_name, filename_hint] if value]
    expected_level = _extract_course_level(course_name) or _extract_course_level(filename_hint)

    for course in candidates:
        score = max((_course_similarity(reference, course.name) for reference in reference_names), default=0.0)
        candidate_level = _extract_course_level(course.name)
        if expected_level and candidate_level:
            if expected_level == candidate_level:
                score += 0.35
            else:
                score -= 0.6
        if score > best_score:
            best_score = score
            best_match = course

    if best_match and best_score >= 0.72:
        return best_match.name, _normalize_course_code(best_match.code)
    return None


def _course_similarity(left, right):
    return SequenceMatcher(None, _normalize_course_label(left), _normalize_course_label(right)).ratio()


def _normalize_course_label(value):
    normalized = (value or '').lower()
    replacements = {
        '&': ' and ',
        '/': ' ',
        '-': ' ',
        'acct': 'accounting',
        'acconting': 'accounting',
        'finan': 'financial',
        'mngement': 'management',
        'mangement': 'management',
        'nonprofit': 'non profit',
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    return re.sub(r'\s+', ' ', normalized).strip()




def _extract_course_level(value):
    tokens = re.findall(r'\b(i{1,3}|iv|[1-4])\b', (value or '').lower())
    if not tokens:
        return ''
    token = tokens[-1]
    return {'1': 'i', '2': 'ii', '3': 'iii', '4': 'iv'}.get(token, token)


def _course_hint_from_filename(original_name):
    stem = os.path.splitext(os.path.basename(original_name or ''))[0]
    if not stem:
        return ''

    hint = stem.replace('_', ' ')
    hint = re.sub(r'\s+\d+$', '', hint)
    hint = re.sub(r'\s+\([^)]+\)$', '', hint).strip()
    hint = re.sub(r'\s+', ' ', hint)
    return hint
