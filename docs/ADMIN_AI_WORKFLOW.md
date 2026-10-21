# Admin AI workflow

## Step 1: extract questions into a selected paper

Implemented in the backend and admin; deployment and a real provider smoke test
are separate checks. This step extracts existing questions. To generate new
questions from notes, use Step 2 below.

1. Open **Exams & quizzes → Exam papers**, create/save or open a paper, then
   scroll to **Quick Actions → Extract questions with AI**.
2. Choose one processed inbox file or one existing resource with extracted text.
   Sources must contain between 50 and 40,000 characters. Uploads still use the
   existing file-processing workflow; this form does not download URLs or run OCR.
3. For a course paper, set its Course first. Optionally choose an existing chapter
   if the whole source belongs to that chapter. Leave it blank for mixed papers
   and organize the questions during review. For exit exams, set Department;
   a course or chapter is not required.
4. Click **Queue extraction**. The existing worker performs the Gemini calls.
   Refresh the page to see status, request attempts, errors and draft counts.
5. Open **Review questions**. Each draft is already assigned to the paper and
   optional chapter; the selected chapter also becomes a topic tag. Use bulk
   metadata editing to organize mixed papers after reviewing the source.
6. Check wording, options A–F, answers, explanations and chapter/topic assignments.
   Missing answers remain unconfirmed. Activate only reviewed questions.

The inbox list's AI action now opens target selection for one file. It does not
immediately create unassigned questions.

## Step 2: generate a new practice paper

Implemented in the backend and admin; deployment and a live Gemini smoke test
remain separate checks.

1. Open **Exams & quizzes → Exam papers → Generate practice paper with AI**.
2. Enter a title, year, duration and access level (Free is the default).
   Choose **Practice quiz** and a course, or **Exit exam — model** and a
   department with no course. Official exams and final papers are not generation
   targets. An optional chapter must belong to the selected course.
3. Choose one processed inbox file or resource with 50–40,000 characters of
   extracted text. To use a new upload, process it through the inbox first.
4. Choose 1–30 questions, one question type, a difficulty target and an optional
   topic focus. All five existing question types are supported. Difficulty is
   a requested target, not a measured quality score.
5. Click **Generate draft paper**. This immediately creates an inactive paper
   and queues the existing worker. Refresh **Your recent generation jobs** for
   status and the **Review questions** link.
6. Review every question, suggested answer, explanation and source excerpt under
   **AI source**. Excerpts must occur literally in the saved source after
   whitespace normalization; this does not prove the suggested answer is correct.
   Essay and matching responses require manual review.
7. Activate approved questions, then activate the paper when it is ready.
   Nothing is published automatically. Generation stops if the paper is activated
   early or changed into an official/final exam.

Each fresh form creates a new variation with its own paper and questions, even
when the source is the same. Reposting the same signed form reuses its job and
does not create another paper. Form tokens belong to the requesting admin and
expire after an hour. Generated questions are not moved from existing papers.

Generation runs in batches of up to 10 questions, saving each validated batch
before requesting the next. Each batch sends the selected source text again.
Retries reuse completed batches; fresh variations
make new provider requests and do not reuse another generation's output. All
batches must pass validation before any questions are created. Invalid output
leaves an inactive paper and a visible failed job for review; no partial question
set is published. A short source may not support the requested question count;
reduce the count rather than treating missing output as a complete paper.

## Step 3: review quality, organize chapters and prepare revision

Implemented as **Exam papers → open a paper → Quick Actions → Review questions &
chapter coverage**. AI job lists also link to this screen. It works with manual,
imported and AI-created questions and shows 25 questions per page.

1. Read the question, options, saved/suggested answer, explanation and available
   source excerpt together. Staff with AI-job permission can open the full saved
   source snapshot. AI-generated answers still require human verification.
2. Fix structural blockers through **Edit question**: missing/invalid answers,
   repeated option values, wrong type/option shapes, mismatched or inactive
   chapters, unverified generated source excerpts, or repeated question text
   within this paper. Repeated-text checks ignore case and surrounding spaces;
   they do not detect paraphrases or prove that two questions are equivalent.
3. For unassigned course questions, consider the **title-word match** chapter
   suggestion. It compares question words with existing active chapter titles,
   declines tied matches and makes no provider call. It is a navigation aid,
   not an AI semantic classification or a confidence score. Select a chapter
   explicitly; nothing is assigned automatically.
4. Select questions and choose **Save chapter choices**, or use those choices
   while activating reviewed questions. The chosen chapter's tag replaces the
   prior chapter tag; granular topic tags are preserved. Use the existing
   question editor for granular topics or removing chapter assignments.
5. Check **I checked the selected answers and source material**, then click
   **Activate reviewed questions**. A blocking issue prevents changes to the
   whole selected set. Changes to displayed content, paper course/type or paper
   visibility require a fresh review; expired/tampered selections are rejected.
   Activation records the admin action. The paper's visibility is a separate
   decision: activating questions in an already active paper exposes them.
6. Use **Chapter coverage in this paper** to compare assigned and active counts.
   These are assignment counts, not evidence of complete syllabus coverage.
   Department-wide exit papers have no course-chapter coverage table.
7. **Prepare revision paper** opens a fresh generation form with the course,
   chapter, topic focus and accessible original source selected. Review settings
   and submit explicitly to request generation. This creates a separate paper
   with new questions. A source may not cover a selected chapter; choose suitable
   material rather than assuming an assignment gap is covered by that source.

Viewing coverage, suggesting chapters and reviewing drafts make no Gemini calls.
Queries and displayed question content are bounded by the page size; shared
source snapshots and chapter choices are loaded together. No new worker,
database tables or migrations are required for this step. Existing question
editor and bulk activation tools remain available; the new review checks apply
to actions submitted through this review screen, not a global publication gate.

## Source references and repeated requests

Questions link to their extraction record under **AI source**. Staff with
permission to view extraction jobs can inspect the original source link, saved
source label, immutable source-text snapshot, target, requester and output.
Snapshots remain when the original source is edited or deleted. These are
document-level references, not verified page-level citations.

In extraction mode, there is one extraction per inbox file and one per resource. Repeating a request
for the same target returns the existing job. Choosing a different target does
not move prior work or create another batch. Review and assign existing drafts
instead. Older unassigned inbox extractions are not guessed/backfilled into a
paper; use the existing Questions assignment action for those records.

Completed extraction results with matching text hash and model/prompt version can be reused
for another source without a new Gemini call. This saves provider work; it does
not deduplicate questions across different source records or papers. Review
content before activation.

## Costs, limits and quota

The backend uses the existing Gemini integration and worker, with no extra
always-running AI service or vector database. Selecting a source and submitting
the form does not make a provider request in the web process.

- Input is bounded to 40,000 characters; extraction output to 500 questions and
  generation output to 30 questions per job.
- Completed extraction chunks of 8,000 characters are saved before proceeding, so retries can
  resume. Existing worker attempt and subprocess limits still apply.
- `AI_MAX_CALLS_PER_JOB` defaults to 10 provider request attempts, including
  failures/retries. Cache hits require no provider call. The displayed number is
  an attempt count, not a token count or bill estimate.
- HTTP 429 responses delay pending AI jobs by `AI_QUOTA_RETRY_SECONDS` (default
  1,800 seconds). New jobs also observe the recorded cooldown. Other worker jobs
  remain eligible. Retries are bounded and eventually require admin review.
- Missing keys and permanent request/configuration errors require review.
  Provider error bodies and credentials are not included in job errors.
- Manual retry preserves completed chunks and the lifetime request counter;
  it does not reset the cost limit. An operator can review and adjust the limit
  deliberately if needed.

These controls do not verify or change Google's billing tier. Use the intended
project/key and check its quota in AI Studio. Free-tier content may be used by
Google to improve products: do not send student records, payment data or
confidential material through that tier. See [Google's data-use terms](https://ai.google.dev/gemini-api/terms#unpaid-services).

## Permissions and deployment

Extraction requires change permission for exam papers and add permission for
questions. Generation also requires add permission for exam papers. Source selectors
require view/change permission for the respective source model; course, department
and chapter choices require view/change permission for those models. Source
snapshots in Operations require view/change question-extraction permission.

Apply migrations through `bot.0004_practice_paper_generation` and
`quiz.0015_practice_paper_generation` before updated web/worker processes start. The
source relationship now supports multiple generation jobs while database
constraints preserve one extraction per source. Existing
jobs and questions remain; the provenance link starts empty for old questions.
Old queued jobs whose prompt/model version differs from the deployed version
stop for review before making a new provider request, rather than mixing
different extraction versions. Review their saved chunks/source before deciding
how to recover them.

Automated verification uses mocked provider responses and disposable databases.
A production smoke test should use a short non-sensitive sample, confirm worker
completion and inactive drafts, then review the saved source reference. No live
Gemini call or production extraction is triggered by the implementation tests.

## Further work

Live Gemini extraction/generation and the deployed review screen still need a
production smoke test. More advanced semantic topic suggestions or revision
based on student mistakes can follow actual admin feedback. Shared-question
reuse needs an explicit design because questions currently belong to one paper.
