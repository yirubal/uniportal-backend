"""
apps/quiz/importers.py

Handles importing questions from an Excel file into a given ExamPaper.
Used by the admin upload action on ExamPaper.
"""

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

VALID_TYPES = {'mcq', 'true_false', 'fill_blank', 'matching', 'essay'}
VALID_DIFFICULTIES = {'easy', 'medium', 'hard'}
VALID_OPTIONS = {'a', 'b', 'c', 'd', 'e'}


class ImportResult(NamedTuple):
    created: int
    skipped: int
    errors: list[str]


def import_questions_from_excel(file, exam_paper) -> ImportResult:
    """
    Reads an uploaded Excel file and creates Question records
    linked to the given ExamPaper.

    Returns ImportResult(created, skipped, errors).
    """
    try:
        import openpyxl
    except ImportError:
        return ImportResult(0, 0, ["openpyxl is not installed. Run: pip install openpyxl"])

    from apps.quiz.models import Question

    try:
        wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    except Exception as e:
        return ImportResult(0, 0, [f"Could not open Excel file: {e}"])

    # Support both 'Questions' sheet name and first sheet
    if "Questions" in wb.sheetnames:
        ws = wb["Questions"]
    else:
        ws = wb.active

    rows = list(ws.iter_rows(values_only=True))

    if len(rows) < 3:
        return ImportResult(0, 0, ["File has no data rows. Make sure you start from row 3."])

    # Row 1 = headers, Row 2 = notes, Row 3+ = data
    header_row = [str(h).strip().lower() if h else "" for h in rows[0]]

    def col(name):
        try:
            return header_row.index(name)
        except ValueError:
            return None

    # Map column indices
    COL = {
        "question_type":  col("question_type"),
        "question":       col("question"),
        "option_a":       col("option_a"),
        "option_b":       col("option_b"),
        "option_c":       col("option_c"),
        "option_d":       col("option_d"),
        "option_e":       col("option_e"),
        "correct_option": col("correct_option"),
        "explanation":    col("explanation"),
        "difficulty":     col("difficulty"),
        "topic_tags":     col("topic_tags"),
        "year_source":    col("year_source"),
    }

    if COL["question_type"] is None or COL["question"] is None:
        return ImportResult(0, 0, [
            "Could not find required columns 'question_type' and 'question'. "
            "Make sure you are using the official template."
        ])

    def get(row, key):
        idx = COL.get(key)
        if idx is None or idx >= len(row):
            return ""
        val = row[idx]
        return str(val).strip() if val is not None else ""

    created = 0
    skipped = 0
    errors = []

    data_rows = rows[2:]  # skip header + notes

    for row_num, row in enumerate(data_rows, start=3):
        # Skip completely empty rows
        if all(v is None or str(v).strip() == "" for v in row):
            continue

        q_type = get(row, "question_type").lower()
        q_text = get(row, "question")

        if not q_text:
            errors.append(f"Row {row_num}: skipped — question text is empty.")
            skipped += 1
            continue

        if q_type not in VALID_TYPES:
            errors.append(
                f"Row {row_num}: skipped — unknown question_type '{q_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_TYPES))}."
            )
            skipped += 1
            continue

        # Options
        option_a = get(row, "option_a")
        option_b = get(row, "option_b")
        option_c = get(row, "option_c")
        option_d = get(row, "option_d")
        option_e = get(row, "option_e")
        correct  = get(row, "correct_option")

        # Enforce true_false options
        if q_type == "true_false":
            option_a = "True"
            option_b = "False"
            option_c = option_d = option_e = ""
            if correct.lower() not in ("a", "b", "true", "false", ""):
                correct = ""
            elif correct.lower() == "true":
                correct = "a"
            elif correct.lower() == "false":
                correct = "b"

        # Normalize correct_option for MCQ/true_false
        if q_type in ("mcq", "true_false"):
            correct = correct.lower()
            if correct not in VALID_OPTIONS:
                correct = ""

        # Essay/matching — no correct option
        if q_type in ("essay", "matching"):
            correct = ""

        # Difficulty
        difficulty = get(row, "difficulty").lower()
        if difficulty not in VALID_DIFFICULTIES:
            difficulty = "medium"

        # Topic tags
        raw_tags = get(row, "topic_tags")
        if raw_tags:
            topic_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        else:
            topic_tags = []

        # Year source
        year_source = get(row, "year_source")

        # Explanation
        explanation = get(row, "explanation")

        try:
            Question.objects.create(
                exam_paper=exam_paper,
                question_type=q_type,
                text=q_text,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                option_e=option_e,
                correct_option=correct,
                explanation=explanation,
                difficulty=difficulty,
                topic_tags=topic_tags,
                year_source=year_source,
                is_active=False,  # admin reviews before activating
            )
            created += 1
        except Exception as e:
            errors.append(f"Row {row_num}: failed to save — {e}")
            skipped += 1

    return ImportResult(created=created, skipped=skipped, errors=errors)