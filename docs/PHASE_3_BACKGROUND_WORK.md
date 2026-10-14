# Phase 3 — Durable background work

Implemented on 2026-10-08. Repository checks and the local recovery drill pass.
Railway deployment, hosted CI, real OCR smoke execution, and live Telegram/Gemini
verification remain pending. Existing student access is unchanged.

## Runtime and work records

Run the existing Django web service and **one** separate worker:

```bash
python manage.py run_worker
```

PostgreSQL stores the queue. No Redis, Celery, or new infrastructure provider is
required. The worker processes one item at a time, rotating through update,
notification, inbox, exam, and AI work. Each item runs in a child process so OCR
memory is released after completion and a stuck library can be terminated.
Document work can delay subsequent messages; measure backlog before increasing
concurrency. No production cost saving or latency improvement has been measured.

- `TelegramUpdate` holds webhook payloads, unique by Telegram update ID.
- Existing `FileInbox` records queue text extraction.
- Existing `ExamPDFUpload` records queue schedule/attendance imports.
- `NotificationDelivery` holds delivery intent and per-recipient progress.
- `QuestionExtraction` holds AI input, completed chunks, results, and progress.

Webhook requests validate update IDs, persist/deduplicate the payload, and return
success without calling Telegram or extracting files. Persistence failure
returns 503 so Telegram can retry. Handler failures now reach the worker instead
of being swallowed by the Telegram application.

Payment creation, approval, and rejection persist student/admin notification
intents in the same database transaction as the business change. Workers see
only committed records. A database failure rolls back the change and its intent;
a later Telegram delivery failure preserves the committed payment state and
schedules delivery retry. Approved payments remain protected from rejection.

Admin AI and broadcast actions return after queueing. Exam uploads are processed
automatically by the worker; the old daemon-thread start action is removed.
Broadcast history shows delivered, remaining, and failed counts. Delivered
recipients are retained across restarts and excluded from subsequent claims.
Exam reminders use the same durable deliveries, with actual delivery totals in
`ExamNotificationLog`.

## Claims, retries, and interruption

Every queue record has attempt count, claim timestamp/token, next eligible time,
and a visible error. Conditional database updates allow one claimant per record.
Old tokens cannot complete replacement claims.

Defaults are defined in `config/settings/base.py`:

| Control | Default |
|---|---|
| Worker concurrency | 1 |
| Idle polling | 2 seconds |
| Stale-claim scan | Every minute |
| Child deadline | 300 seconds |
| Claim expiry | 900 seconds |
| Maximum automatic attempts | 5 |
| Retry delay | 30, 60, 120, 240 seconds; capped at 3600 |

Claim expiry must exceed the child deadline. The worker terminates the whole
child process group on timeout or graceful shutdown, including OCR descendants.
Temporary downloads/extraction files live under that child's temporary directory
and are removed by the parent. A forcibly killed parent may leave temporary
files until platform/container cleanup; scheduled orphan retention is Phase 4.

Only stale processing claims are recovered. Fresh claims and failed records are
left alone. Legacy processing rows without claim timestamps are considered
interrupted work. Invalid inputs/unsupported documents and permanent Telegram
errors stop for review; transient failures retry within the attempt limit.
Telegram `retry_after` is respected, including delaying other pending
notification deliveries when a delivery hits a rate limit.

Bot admin pages expose statuses, errors, retry times, and explicit failed-record
retry actions. File Inbox and Exam PDF Upload have equivalent retry controls.
These actions reset attempts only for failed records, after administrator review.
`run_bot` is now one-off stale recovery; it does not reset every failed item.
`process_exam_pdfs` is a one-off command using the same claims and child deadline.

Delivery is **at least once**, not exactly once: a provider may accept a message
or paid AI call just before the child dies, before the local result is saved.
A retry can repeat that external operation. Saved delivery/chunk results prevent
repeating known completed work; no unsupported exactly-once promise is made.

## Extraction limits and caching

OCR uses pytesseract's timeout argument and pdf2image's render timeout, with one
page rendered at a time, one render thread, grayscale, and a bounded image size.
There are no thread-incompatible signal alarms or all-page rendering fallback.
An unreadable page count fails visibly instead of rendering an unknown document.
The digital PDF path uses APIs available in the pinned pdfplumber version.

PDF extraction is limited to 100 pages. OCR has a 240-second document budget;
large scanned PDFs above 5 MiB require review. Large digital PDFs within the page
limit still use text extraction. Unsupported files and empty results fail for
review; partial text is retained with an explicit warning and `partial` outcome.
Mixed digital/scanned PDFs flag image-only pages for review instead of claiming
complete text extraction. Images above 20 million pixels require review before
decoding. Image/Word/PDF processing also remains subject to the child deadline. Broader
upload validation and storage retention remain Phase 4 work.

AI inputs are bounded to 40000 characters, split into 8000-character chunks.
Calls have a 60-second SDK HTTP timeout and an 8000-token output limit. Output
must be valid JSON with valid types/field lengths; truncated output is no longer
silently repaired into an incomplete successful extraction. Generated questions
are created atomically as inactive drafts with their actual question types.
Administrators must classify and review them before publication.

Each completed chunk is persisted immediately. A retry reuses saved chunks.
Completed extractions are reused for identical normalized input text and the
same extraction/model version. Repeating the admin action on the same inbox
does not create another job or duplicate drafts. Source and results are retained
for review; changed-input re-extraction requires an explicit reviewed operation.

Set `GEMINI_MODEL` on the worker; the default is `gemini-3.1-flash-lite`. Google
lists the formerly hardcoded `gemini-2.0-flash-lite` as shut down and names that
replacement. Model choice changes cache version and should be reviewed for cost
and extraction quality. No paid provider calls were made during this work.
[Google model lifecycle](https://ai.google.dev/gemini-api/docs/deprecations/).

Files use unique temporary paths and sanitized filenames. Inbox identity now
uses `(telegram_chat_id, telegram_message_id)`, not message ID alone. Historical
rows retain unknown chat ID `0`; the configured original `TELEGRAM_CHANNEL_ID`
can identify them when seen again. Confirm/backfill their actual source before
enabling ingestion from multiple channels. A configured source channel is
checked by the handler; production webhook-secret enforcement remains Phase 6.

## Railway rollout and scheduled maintenance

1. Stop old processing commands/threads during the release and back up the database.
2. Apply migrations before starting the new web/worker code:
   `python manage.py migrate`. New migrations are content 0015, exams 0005,
   and bot 0001–0002. Existing failed items remain failed for review.
3. Configure a worker service from the same repository/image with start command
   `python manage.py run_worker`, one replica, the same PostgreSQL and R2 settings,
   Telegram/Gemini credentials, and `GEMINI_MODEL`. Give it a restart policy and
   no HTTP healthcheck or public domain. The Docker worker shares local media;
   separate Railway services must share R2 because container disks are separate.
4. Keep the web start command for Gunicorn. `Procfile` names the worker command,
   but the running Railway service settings still need verification/configuration.
5. Register/verify the existing webhook with its secret, then check that accepted
   updates progress to processed rows and inbox files. Check payment and broadcast
   deliveries, exam imports, and inactive AI drafts using a controlled test case.

Railway documents separate always-running workers and scheduled services.
[Railway worker guide](https://docs.railway.com/guides/cron-workers-queues).

Use one daily scheduled service for maintenance, with start command:

```bash
python manage.py run_maintenance
```

Set `0 3 * * *` (03:00 UTC / 06:00 Nairobi). It expires lapsed subscriptions,
queues due 15/7/3-day exam reminders, and cleans at most 100 assigned inbox
references. Duplicate reminder runs use persisted recipient keys. Subscription
warning notifications remain optional via `check_subscriptions --notify`;
maintenance does not automatically add those messages during free adoption.
The scheduled service needs the same database/storage settings and exits when
finished. Railway schedules run in UTC and skip a new execution when the previous
one is still running. [Railway cron guide](https://docs.railway.com/cron-jobs).

The live worker and schedule have **not** been configured from this workspace.
Compare worker memory, CPU, queue age, and Railway usage against Phase 1 metrics.
Leave worker concurrency at one until workload evidence supports a change.

## Verification

- PostgreSQL 18.6: the full 134-test suite passed, followed by 36 focused worker/
  exam checks for the final changes, including the additional mixed-PDF test.
- SQLite: 135 tests ran, 128 passed and seven PostgreSQL checks skipped.
- System checks, migration drift, and diff whitespace checks pass.
- Synthetic backup/restore passes with the new queue schema.
- Real child-process kill/restart drill passes: fresh claims are protected,
  stale work is reclaimed, replacement processing completes once, and notification
  retries persist. No external services are contacted.
- A real digital PDF fixture verifies the pinned parser; OCR unit tests verify
  bounded rendering, timeout arguments, and partial-result behavior.
- Tesseract is absent locally. The real image OCR smoke check is therefore
  skipped locally and required in PostgreSQL CI, which installs Tesseract/Poppler.
  Hosted CI and live provider/storage behavior remain unverified.

For a disposable local PostgreSQL server with CREATEDB rights:

```bash
DATABASE_URL=postgresql://... python scripts/check_worker_recovery.py
DATABASE_URL=postgresql://... python scripts/check_worker_recovery.py --require-ocr
```

Both drills refuse remote hosts and create/drop only a uniquely named disposable
database. The second also requires local Tesseract and checks real image OCR in a
worker child. CI runs it automatically. Stop workers before rolling code/schema
back; reversing these migrations removes queued work and progress records.
