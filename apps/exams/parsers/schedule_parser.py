"""
Parses the Unity University exam schedule PDF (Type 1).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedScheduleEntry:
    course_name: str
    course_code: str
    total_students: int
    rooms: List[str]


@dataclass
class ParsedScheduleSession:
    session_number: int
    date: date
    start_time: time
    end_time: time
    entries: List[ParsedScheduleEntry] = field(default_factory=list)


@dataclass
class ParsedSchedule:
    year: int
    term: int
    center: str
    sessions: List[ParsedScheduleSession] = field(default_factory=list)

    @property
    def earliest_date(self):
        if not self.sessions:
            return None
        return min(session.date for session in self.sessions)


def parse_schedule_pdf(file_path: str) -> Optional[ParsedSchedule]:
    try:
        import pdfplumber

        pages_text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True) or page.extract_text()
                if text:
                    pages_text.append(_normalize_schedule_text(text))
    except Exception as exc:
        logger.error('Failed to read schedule PDF: %s', exc)
        return None

    full_text = '\n'.join(pages_text)
    return _parse_schedule_text(full_text, pages_text)


def _parse_schedule_text(full_text: str, pages_text: list) -> Optional[ParsedSchedule]:
    year = None
    term = None
    full_text = _normalize_schedule_text(full_text)
    year_match = re.search(r'(\d{4})\s*-\s*(First|Second|Third)\s+Term', full_text, re.IGNORECASE)
    if year_match:
        year = int(year_match.group(1))
        term_str = year_match.group(2).lower()
        term = {'first': 1, 'second': 2, 'third': 3}.get(term_str, 1)

    if not year:
        logger.error('Could not extract year/term from schedule PDF')
        return None

    center_match = re.search(r'^Center\s*:\s*([^\n\r]+)', full_text, re.IGNORECASE | re.MULTILINE)
    center = center_match.group(1).strip() if center_match else 'Addis Ababa'
    schedule = ParsedSchedule(year=year, term=term, center=center)

    for block in pages_text:
        current_date = None
        current_start_time = None
        current_end_time = None
        current_session = None

        date_match = re.search(
            r'Date\s*:\s*(?:\w+,\s*)?(\w+ \d{1,2},\s*\d{4})',
            block,
            re.IGNORECASE,
        )
        if date_match:
            try:
                current_date = datetime.strptime(
                    date_match.group(1).strip(),
                    '%B %d, %Y',
                ).date()
            except ValueError:
                pass

        time_match = re.search(
            r'Exam Time\s*:\s*(\d{1,2}:\d{2}\s*[AP](?:\.?\s*M)?)\s*-\s*(\d{1,2}:\d{2}\s*[AP](?:\.?\s*M)?)',
            block,
            re.IGNORECASE,
        )
        if time_match:
            try:
                current_start_time = _parse_time_token(time_match.group(1))
                current_end_time = _parse_time_token(time_match.group(2))
            except ValueError:
                pass

        session_match = re.search(
            r'Exam Session\s*:\s*(I{1,3}|IV)',
            block,
            re.IGNORECASE,
        )
        if session_match:
            roman = session_match.group(1).upper()
            current_session = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}.get(roman, 1)

        if current_date and current_session and current_start_time and current_end_time:
            entries = _extract_schedule_entries(block)
            if entries:
                parsed_session = ParsedScheduleSession(
                    session_number=current_session,
                    date=current_date,
                    start_time=current_start_time,
                    end_time=current_end_time,
                    entries=entries,
                )
                existing = next(
                    (
                        session for session in schedule.sessions
                        if session.session_number == current_session and session.date == current_date
                    ),
                    None,
                )
                if not existing:
                    schedule.sessions.append(parsed_session)

    return schedule if schedule.sessions else None


def _extract_schedule_entries(text: str) -> List[ParsedScheduleEntry]:
    entries = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start_index = None
    for index, line in enumerate(lines):
        if 'COURSE NAMES' in line:
            start_index = index + 1
            break

    if start_index is None:
        for index, line in enumerate(lines):
            if re.match(r'^\d+\s+', line):
                start_index = index
                break
    if start_index is None:
        return entries

    row_indices = [
        index
        for index in range(start_index, len(lines))
        if re.match(r'^\d+\s+', lines[index]) and not re.match(r'^\d+\s+[A-Z]-\d+\s*$', lines[index])
    ]

    for position, row_index in enumerate(row_indices):
        next_row_index = row_indices[position + 1] if position + 1 < len(row_indices) else len(lines)
        previous_row_index = row_indices[position - 1] if position > 0 else start_index - 1

        surrounding_prefix = lines[previous_row_index + 1:row_index]
        suffix_lines = lines[row_index + 1:next_row_index]
        if any('N.B:' in line for line in suffix_lines):
            suffix_lines = suffix_lines[:next(index for index, line in enumerate(suffix_lines) if 'N.B:' in line)]

        next_main_line = lines[next_row_index] if next_row_index < len(lines) else ''
        prefix_lines = _collect_prefix_lines(surrounding_prefix, lines[row_index])
        suffix_lines = _trim_next_row_prefix(suffix_lines, next_main_line)
        row_payload = prefix_lines + [lines[row_index]] + suffix_lines

        course_code = _extract_course_code(' '.join(row_payload))
        if not course_code:
            continue

        course_name = _extract_course_name(row_payload)
        if not course_name:
            continue

        rooms = []
        for line in row_payload:
            rooms.extend(re.findall(r'[A-Z]-\d+', line))

        total_students = _extract_total_students(lines[row_index], course_code)

        entries.append(
            ParsedScheduleEntry(
                course_name=course_name,
                course_code=course_code,
                total_students=total_students,
                rooms=rooms,
            )
        )

    return entries


def _normalize_schedule_text(text: str) -> str:
    normalized = (
        text.replace('–', '-')
        .replace('—', '-')
        .replace('“', '"')
        .replace('”', '"')
    )

    lines = []
    for raw_line in normalized.splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line:
            continue
        line = re.sub(r'\bC\s+e\s+n\s+t\s+e\s+r\b', 'Center', line, flags=re.IGNORECASE)
        lines.append(line)

    return '\n'.join(lines)


def _parse_time_token(value: str) -> time:
    normalized = value.upper().replace('.', '').replace(' ', '')
    return datetime.strptime(normalized, '%I:%M%p').time()


def _collect_prefix_lines(lines: List[str], main_line: str) -> List[str]:
    if not _main_line_needs_prefix(main_line):
        return []

    prefix = []
    for line in reversed(lines):
        if _looks_like_course_prefix(line):
            prefix.append(line)
            if _extract_course_code(line):
                break
            continue
        break
    return list(reversed(prefix))


def _trim_next_row_prefix(lines: List[str], next_main_line: str) -> List[str]:
    trimmed = list(lines)
    if not _main_line_needs_prefix(next_main_line):
        return trimmed

    while trimmed and _looks_like_course_prefix(trimmed[-1]):
        trimmed.pop()
        break
    return trimmed


def _looks_like_course_prefix(line: str) -> bool:
    if 'N.B:' in line or 'Exam Session' in line or 'Date:' in line:
        return False
    if re.search(r'[A-Z]-\d+', line):
        return False
    if re.fullmatch(r'[\d\s-]+', line):
        return False
    return bool(re.search(r'[A-Za-z]', line))


def _main_line_needs_prefix(line: str) -> bool:
    payload = re.sub(r'^\d+\s+', '', line or '').strip()
    if not payload:
        return False
    if _extract_course_code(payload) and re.search(r'[A-Za-z]', re.sub(r'([A-Za-z]{2,6})\s*(\d{3,4}[A-Za-z]?)', '', payload)):
        return False
    return True


def _extract_course_code(text: str) -> str:
    match = re.search(r'([A-Za-z]{2,6})\s*(\d{3,4}[A-Za-z]?)', text)
    if not match:
        return ''
    return f'{match.group(1).upper()} {match.group(2).upper()}'


def _extract_total_students(main_line: str, course_code: str) -> int:
    payload = re.sub(r'^\d+\s+', '', main_line)
    payload = payload.replace(course_code, '').replace(course_code.replace(' ', ''), '')
    match = re.search(r'(\d+)', payload)
    return int(match.group(1)) if match else 0


def _extract_course_name(row_lines: List[str]) -> str:
    parts = []
    for index, line in enumerate(row_lines):
        cleaned = line
        if index == 0 or re.match(r'^\d+\s+', line):
            cleaned = re.sub(r'^\d+\s+', '', cleaned)
        cleaned = re.sub(r'([A-Za-z]{2,6})\s*(\d{3,4}[A-Za-z]?)', '', cleaned)
        cleaned = re.sub(r'[A-Z]-\d+', '', cleaned)
        cleaned = re.sub(r'\b\d+\b', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -')
        if cleaned:
            parts.append(cleaned)

    return ' '.join(parts).strip()
