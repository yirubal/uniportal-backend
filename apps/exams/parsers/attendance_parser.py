"""
Parses Unity University attendance sheet PDFs (Type 2).
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedStudent:
    name: str
    student_id: str
    department: str


@dataclass
class ParsedAttendancePDF:
    year: int
    term: int
    exam_date: date
    session_num: int
    start_time: time
    end_time: time
    room_code: str
    course_name: str
    course_code: str
    students: List[ParsedStudent]


def parse_attendance_pdf(file_path: str) -> List[ParsedAttendancePDF]:
    text = _extract_pdf_text(file_path)
    if not text:
        return []
    return _parse_attendance_text(text)


def _parse_attendance_text(text: str) -> List[ParsedAttendancePDF]:
    text = _normalize_attendance_text(text)
    block_pattern = re.compile(r'(?=Unity University\b)', re.IGNORECASE)
    blocks = [block.strip() for block in block_pattern.split(text) if block.strip()]
    parsed_blocks = []

    if not blocks:
        parsed = _parse_attendance_block(text)
        return [parsed] if parsed else []

    for block in blocks:
        parsed = _parse_attendance_block(block)
        if parsed:
            parsed_blocks.append(parsed)
        else:
            logger.warning('Skipping unparseable attendance block')

    return parsed_blocks


def _extract_pdf_text(file_path: str) -> str:
    try:
        import pdfplumber

        pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(layout=True) or page.extract_text()
                if page_text and page_text.strip():
                    pages.append(page_text)

        extracted = '\n'.join(pages).strip()
        if extracted:
            return extracted
    except Exception as exc:
        logger.error('Failed to read attendance PDF %s: %s', file_path, exc)

    try:
        from apps.bot.processor import extract_pdf_with_ocr

        return extract_pdf_with_ocr(file_path)
    except Exception as exc:
        logger.error('Attendance OCR fallback failed for %s: %s', file_path, exc)
        return ''


def _normalize_attendance_text(text: str) -> str:
    normalized = (
        text.replace('“', '"')
        .replace('”', '"')
        .replace('’', "'")
        .replace('–', '-')
        .replace('—', '-')
    )
    normalized = re.sub(r'\bA\.\s*M\b', 'AM', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\bP\.\s*M\b', 'PM', normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r'\(([\d\s]{4,8})\s+(I{1,3}|IV)\s+Term\)',
        _collapse_year_term_spacing,
        normalized,
        flags=re.IGNORECASE,
    )

    lines = []
    for raw_line in normalized.splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


def _parse_attendance_block(text: str) -> Optional[ParsedAttendancePDF]:
    year = None
    term = None
    yt_match = re.search(r'\(([\d\s]{4,8})\s+(I{1,3}|IV)\s+Term\)', text, re.IGNORECASE)
    if yt_match:
        year = int(re.sub(r'\s+', '', yt_match.group(1)))
        term_str = yt_match.group(2).upper()
        term = {'I': 1, 'II': 2, 'III': 3, 'IV': 1}.get(term_str, 1)

    if not year:
        logger.error('Could not extract year/term')
        return None

    exam_date = None
    date_match = re.search(
        r'Exam Date:\s*(?:\w+,\s*)?([A-Za-z]+ \d{1,2},\s*\d{4})',
        text,
        re.IGNORECASE,
    )
    if date_match:
        try:
            exam_date_value = re.sub(r',\s*', ', ', date_match.group(1).strip())
            exam_date = datetime.strptime(exam_date_value, '%B %d, %Y').date()
        except ValueError:
            pass

    if not exam_date:
        logger.error('Could not extract exam date')
        return None

    session_num = None
    start_time = None
    end_time = None
    session_match = re.search(
        r'(?:Exam\s+Session|Session|ession)\s*:\s*(I{1,3}|IV)\s*:\s*'
        r'(\d{1,2}:\d{2}\s*[AP](?:\.?\s*M)?)\s*[-]\s*(\d{1,2}:\d{2}\s*[AP](?:\.?\s*M)?)',
        text,
        re.IGNORECASE,
    )
    if session_match:
        roman = session_match.group(1).upper()
        session_num = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}.get(roman, 1)
        try:
            start_time = _parse_time_token(session_match.group(2))
            end_time = _parse_time_token(session_match.group(3))
        except ValueError as exc:
            logger.warning('Time parse error: %s', exc)

    if not session_num:
        logger.error('Could not extract session number')
        return None

    room_code = None
    room_match = re.search(r'EXAM\s+ROOM:\s*([A-Z]\s*-\s*\d+)', text, re.IGNORECASE)
    if room_match:
        room_code = re.sub(r'\s*-\s*', '-', room_match.group(1).strip().upper())

    if not room_code:
        logger.error('Could not extract room code')
        return None

    course_name, course_code = _extract_course_details(text)

    if not course_name:
        logger.error('Could not extract course')
        return None

    students = _extract_students(text)

    return ParsedAttendancePDF(
        year=year,
        term=term,
        exam_date=exam_date,
        session_num=session_num,
        start_time=start_time,
        end_time=end_time,
        room_code=room_code,
        course_name=course_name,
        course_code=course_code,
        students=students,
    )


def _parse_time_token(value: str) -> time:
    normalized = value.upper().replace('.', '').replace(' ', '')
    return datetime.strptime(normalized, '%I:%M%p').time()


def _extract_course_details(text: str) -> tuple[str, str]:
    course_match = re.search(
        r'LIST OF EXAMINEES FOR\s*(.+?)(?=\n(?:SN\b|S\s*N\b|S Name\b|\d+\s+|Attendance of Students|Name of Invigilator)|$)',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not course_match:
        return '', ''

    header = ' '.join(course_match.group(1).split()).strip().strip('"').strip()
    header = re.sub(r'\s+', ' ', header)

    code_match = re.search(r'\(\s*([A-Za-z]{2,6}\s*\d{3,4}[A-Za-z]?)\s*\)?\s*$', header)
    if code_match:
        course_code = _normalize_course_code(code_match.group(1))
        course_name = header[:code_match.start()].strip()
    else:
        course_code = ''
        course_name = re.sub(r'\(\s*\)?\s*$', '', header).strip()

    course_name = course_name.strip('"').strip().rstrip('(').strip()
    return course_name, course_code


def _collapse_year_term_spacing(match: re.Match) -> str:
    year = re.sub(r'\s+', '', match.group(1))
    return f'({year} {match.group(2)} Term)'


def _extract_students(text: str) -> List[ParsedStudent]:
    students = []
    for main_line, continuations in _collect_student_rows(text):
        match = re.match(
            r'^(?:\d+\s+)?(.+?)\s+(\d{4,6}|\*{1,6}|#{4,6})\s+([MF])\s+([A-Za-z][A-Za-z\s&./-]+)$',
            main_line,
        )
        if not match:
            continue

        name = match.group(1).strip()
        if continuations:
            name = f"{name} {' '.join(continuations)}".strip()

        student_id = match.group(2).strip()
        department = match.group(4).strip()

        if re.match(r'^[\*#]+$', student_id):
            student_id = ''
        if name.upper() in ['NAME', 'NAME OF EXAMINEES']:
            continue

        students.append(
            ParsedStudent(
                name=name,
                student_id=student_id,
                department=department,
            )
        )
    return students


def _collect_student_rows(text: str) -> List[tuple[str, List[str]]]:
    lines = text.splitlines()
    start_index = None
    end_index = len(lines)

    for index, line in enumerate(lines):
        if 'Name of Examinees' in line:
            start_index = index + 1
            break

    if start_index is None:
        for index, line in enumerate(lines):
            if re.match(r'^\d+\s+', line):
                start_index = index
                break
    if start_index is None:
        return []

    for index in range(start_index, len(lines)):
        if 'Attendance of Students with valid cases' in lines[index] or 'Name of Invigilator' in lines[index]:
            end_index = index
            break

    rows: List[tuple[str, List[str]]] = []
    current_main = ''
    current_continuations: List[str] = []

    for raw_line in lines[start_index:end_index]:
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line or re.match(r'^\d+\s*$', line):
            continue

        if _looks_like_student_line(line):
            if current_main:
                rows.append((current_main, current_continuations))
            current_main = line
            current_continuations = []
            continue

        if current_main and re.search(r'[A-Za-z]', line):
            current_continuations.append(line)

    if current_main:
        rows.append((current_main, current_continuations))

    return rows


def _looks_like_student_line(line: str) -> bool:
    return bool(
        re.match(
            r'^(?:\d+\s+)?[A-Za-z].+\s+(\d{4,6}|\*{1,6}|#{4,6})\s+[MF]\s+[A-Za-z][A-Za-z\s&./-]+$',
            line,
        )
    )


def _normalize_course_code(course_code: str) -> str:
    compact = re.sub(r'\s+', '', course_code or '')
    match = re.match(r'([A-Za-z]+)(\d{3,4}[A-Za-z]?)$', compact)
    if not match:
        return (course_code or '').strip()
    return f'{match.group(1).upper()} {match.group(2).upper()}'
