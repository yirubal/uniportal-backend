# Importing questions

Open **Exams & quizzes → Exam papers**, save or open the target paper, then
scroll to **Quick Actions → Import Questions from Excel**. Download the template
from that page; its format depends on the paper type.

| Paper type | Paper setup | Spreadsheet organization |
|---|---|---|
| Team Quiz / Final Exam | Choose the course; leave Department blank. | Use the quiz template. Each question needs a chapter, which also becomes a topic tag for selective practice. |
| Exit Exam — Official / Model | Choose the department. Leave Course blank for a department-wide paper. | Use the exit template. Neither course nor chapter is required. Topic tags are optional. |

## Department-wide exit exams

The `course` column can be empty or omitted entirely. The importer never assigns
a course to the paper, even if optional course values are supplied. Questions
belong to the selected paper and can cover several subjects.

Old templates with a `course` column still work. A supplied value must match an
active course name or code. Its canonical course name becomes a topic tag so the
subject information is retained. These tags support exit-exam topic practice;
they do not turn the paper into a course-specific quiz. If the paper already has
a Course selected, a supplied row course must match it. Blank row courses still
work. Existing paper assignments are not changed by imports.

Use `topic_tags`, such as `leadership,ethics`, when students should be able to
practise those topics. Questions without tags are still available in the paper.

The exit importer accepts a `Questions` sheet (case insensitive), or the active
sheet if no such sheet exists. It accepts either `question` or `question_text` as
the question-text column. The template's notes row can be kept or removed.

Question text is required. An omitted question type defaults to MCQ; supplied
types must be valid. MCQ and true/false questions need a valid `correct_option`.
True/false options are filled automatically. Essay and matching questions do not
need a correct-option value. Explanation, difficulty, topic tags and source year
are optional; difficulty defaults to medium.

## Review and retry

Admin imports create **inactive** questions. Review the imported questions, then
use **Activate selected questions** when they are ready.

Imports can partially succeed. Read the created/skipped counts and row errors.
Retry only the skipped rows: uploading the whole workbook again creates another
copy of the rows already imported.

The `import_exit_exam_questions` management command uses the same parser and row
rules. It preserves its existing behavior of creating active questions. Its
`--delete-existing` replacement is rolled back if no new questions import.
