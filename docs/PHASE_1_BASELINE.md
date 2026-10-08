# Phase 1 baseline and operations

Updated: 2026-10-08.

**Status:** Repository baseline implemented and verified locally. Production
measurement and actual backup verification remain open. Phase 1 is not fully
complete until those checks are recorded.

## Product policy: free adoption period

Students should enjoy free access while they become familiar with UniPortal.
Do not introduce paywalls or a paid daily question allowance during this period.
Authentication, ownership of personal records, input validation, and operational
rate/size limits still apply. Subscription data must remain accurate.

The backend currently has no single adoption-mode switch. Existing gates are
listed below to distinguish intended policy from implemented behavior. Phase 1
does not change these routes or grant/revoke subscriptions.

| Code path | Existing restriction |
|---|---|
| `ResourceDownloadView` | A resource labelled premium requires a valid premium subscription. |
| `ResourceSerializer` | Hides the file URL and marks premium resources locked for free students. |
| `ExamPaperSerializer` | Marks premium papers locked for free students. |
| `get_practice_questions` / `get_simulation_questions` | Reject premium papers for free students. Explicit practice limits can also be capped at five. |
| `CourseTopicsView` / `SelectivePracticeView` | Exclude questions from premium papers for free students. |
| `get_topic_questions` | Caps free students at five returned questions per request; does not implement a daily allowance. |
| `PerformanceView` | Requires premium access. |
| `get_exit_exam_questions` | Premium-only helper; not directly exposed by the current API URL configuration. |
| `FreeQuotaNotExceeded` | Defined but unused by current API views; incorrectly shares download counters. |

These gates can conflict with adoption policy depending on content labels and
student state. The deployed dataset and frontend behavior have not been checked.
Changing them should be an explicit follow-up implementing free access, rather
than silently turning inconsistent checks into stronger paid restrictions.

## Local verification

| Check | Result |
|---|---|
| Initial test suite | 85 tests; five failed due to obsolete copy-based storage assumptions. |
| Updated SQLite suite | 92 discovered; 90 passed, two PostgreSQL feature tests skipped. |
| Updated PostgreSQL suite | All 92 passed on isolated PostgreSQL 18.6. |
| Django system checks | Passed. |
| Migration drift | No changes detected. |
| Dependency check | Installed pins match `requirements.txt`; `pip check` passed. |
| Synthetic database/media restore | Passed; all public-table rows and file hashes matched. |
| GitHub Actions | Workflow added; hosted execution awaits pushing this change. |

The local interpreter is Python 3.14.7. CI targets Python 3.12 and PostgreSQL 15,
matching the repository's container configuration. Those CI versions have not
been run locally; the actual Railway Python/PostgreSQL versions remain unknown.

The local development SQLite database has one student and no subscription
requests, resources, inbox items, quiz attempts, or exam PDF uploads. It cannot
represent production traffic, content volume, query latency, or costs.

A synthetic query measurement from the initial review remains the performance
starting point: three resources with prefetched courses execute eight queries
during serialization. Phase 5 will address this; Phase 1 preserves that behavior.

## Storage behavior and safety

Publication reuses the inbox object's storage key. It does not download and
re-upload the file merely to move it into a different folder. Clearing the inbox
reference must leave the resource's file readable.

`clear_inbox_file` now preserves objects referenced by any resource or another
inbox row, as well as an explicitly protected key. A genuine legacy duplicate
can be deleted once the assigned resource's file exists and no other resource
or inbox references the duplicate. Tests cover shared references, cross-resource
references, another inbox, missing destination files, dry runs, repair, and the
periodic cleanup guard.

Cleanup checks are not an object-storage transaction with concurrent publication.
Run manual repair/cleanup during a quiet maintenance window without parallel
publication, after taking a backup. The broader lifecycle belongs to Phase 3/4.

PostgreSQL also exposed a connection-lifecycle bug in `process_exam_pdfs`: closing
connections inside `handle()` aborted the caller's transaction. The command now
leaves cleanup to the CLI or background-thread caller; the existing thread
wrapper already closes its connections in `finally`.

## Repeatable local checks

The test settings use temporary media, in-memory SQLite by default, a test-only
secret, and empty external-service credentials. They do not require copying
production secrets into CI. An explicitly supplied `DATABASE_URL` must identify
a disposable test database whose user can create Django's test database.

```bash
source venv/bin/activate
python manage.py check --settings=config.settings.test
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py test --noinput --settings=config.settings.test
python -m pip check
```

For PostgreSQL, set `DATABASE_URL` to a local disposable database and run the same
commands. To force the SQLite default when your shell already exports a database
URL, prefix each check with `DATABASE_URL=sqlite:///:memory:`.

The two database-specific tests verify concurrent enforcement of one pending
payment request per student, and exact topic-tag matching with inactive content
excluded. They do not claim that payment approval is already concurrency-safe;
that change remains in Phase 2.

The GitHub Actions workflow runs checks, migration drift detection, and the full
suite for SQLite and PostgreSQL. Its PostgreSQL job also runs the synthetic
restore drill. See [workflow](../.github/workflows/checks.yml) and
[GitHub service-container documentation](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

## Deployment inventory

| Item | Evidence / status |
|---|---|
| Hosting | Railway, confirmed by owner. |
| Plan | Hobby, confirmed by owner; owner reports $5 monthly usage credits. |
| CPU/RAM | Actual usage and configured per-service limits unknown. Plan maxima are not usage measurements. |
| Services / replicas / region | Unknown; inspect Railway project. |
| Build / settings / start command | Unknown in production. Docker defaults to `config.settings.docker` and four web workers; Procfile specifies two; WSGI falls back to `config.settings.prod`. |
| Database | PostgreSQL intended by project; actual Railway service, version, volume, and connection path unknown. |
| Media | R2 supported by code; actual bucket usage, visibility, and recovery configuration unknown. |
| Scheduled work | Subscription expiry, exam notifications, and PDF commands exist; deployed schedules unknown. |
| Monthly cost | Actual invoice and service-level usage unknown. |
| Database backups | Current schedule, retention, latest successful backup, and last restore unknown. |
| Media backups | Independent copies and object recovery arrangements unknown. |

## Capture the Railway baseline

Use a consistent window, initially the last seven days. Record dates, timezone,
deployments, and whether traffic was normal or an exam-season spike. Avoid
changing replicas or resource limits until the numbers are captured.

Railway's service Metrics panel reports CPU, memory, disk, and network usage.
It does not directly provide application latency or error-rate measurements:
[Railway metrics documentation](https://docs.railway.com/observability/metrics).

| Measurement | Source | Baseline |
|---|---|---|
| CPU average / peak per service | Service Metrics | Pending |
| Memory average / peak per service | Service Metrics | Pending |
| Volume usage and network traffic | Service Metrics | Pending |
| Monthly actual/projected cost per service | Workspace/project usage and billing | Pending |
| Replica count, worker count, deployed commit | Service settings, actual start command and deployment | Pending |
| Request count and 5xx rate | Existing request logs or telemetry, if available | Pending |
| p50/p95 latency for catalogue, quiz, auth, downloads | Existing telemetry; otherwise record the measurement gap | Pending |
| Slow query time and calls | Existing PostgreSQL statistics/logging, if available | Pending |
| Pending/processing/failed jobs | Read-only aggregate query below | Pending |

Use existing observability first; this phase does not add a monitoring service.
Missing latency/error-rate data is a recorded gap, not a reason to infer that
performance is healthy. CLI usage inspection is also available if already
installed and authenticated: [Railway usage documentation](https://docs.railway.com/cli/usage).

Run this read-only shell command in the configured application environment for
backlog counts. It outputs no student identities or connection secrets:

```bash
python manage.py shell --command="from django.db.models import Count; from apps.content.models import FileInbox; from apps.exams.models import ExamPDFUpload; print('Inbox:', list(FileInbox.objects.values('processing_status').order_by('processing_status').annotate(count=Count('id')))); print('Exam PDFs:', list(ExamPDFUpload.objects.values('status').order_by('status').annotate(count=Count('id'))))"
```

Current processing records do not store sufficient claim timing to reliably
classify stale jobs; add that in Phase 3.

## Backup and restore procedure

### Synthetic check included in CI

On a disposable local PostgreSQL server, with `DATABASE_URL` already configured:

```bash
python scripts/check_backup_restore.py
```

The script requires local PostgreSQL access and database-creation privileges,
creates two unique databases, migrates and seeds synthetic student/course/file
data, then uses `pg_dump` and `pg_restore`. It verifies all restored public-table
rows and a separate media copy, then removes its own databases and temporary
files. Remote server URLs are refused. It never backs up the supplied database.

This verifies the logical restore procedure with synthetic local media. It does
not verify a Railway volume snapshot, a production dump, or R2 object recovery.

### Verify the real backup arrangement

1. Inspect the database service's Backups tab, confirm its volume and schedule,
   and record retention plus the timestamp of the latest successful backup.
   Railway supports scheduled volume backups; purchasing Hobby does not establish
   that a schedule is enabled. See [Railway backup documentation](https://docs.railway.com/volumes/backups).
2. If no suitable schedule exists, configure one on the actual service and
   confirm the first successful backup. Record its cost and recovery window.
3. Confirm media recovery independently. A PostgreSQL backup stores file keys,
   not R2 file bytes. Inspect existing media copies/recovery configuration; arrange
   a separate backup if there is none. Preserve storage keys in the backup.
4. Restore a real logical database backup into a fresh isolated PostgreSQL
   instance, with matching application code and no production Telegram/AI
   credentials. Do not restore over the running service for a rehearsal.
5. Recover representative media into isolated local storage or a test bucket;
   verify file hashes and database references, including shared inbox/resource
   keys. Check profile reads, course/resource links, and quiz history.
6. Record backup date, restore duration, database row counts, sampled file hashes,
   verification outcome, and any missing data. Keep credentials and private
   student data out of repository documentation.

For a portable PostgreSQL logical backup, use a client compatible with the server
major version and supply connection details through the environment or a
protected password file. On the source connection, with `BACKUP_PATH` configured:

```bash
pg_dump --format=custom --file="$BACKUP_PATH"
```

Then configure the connection for an **isolated destination server**, create a
new empty database, and restore into that named database:

```bash
createdb uniportal_restore_check
pg_restore --exit-on-error --no-owner --no-privileges --dbname=uniportal_restore_check "$BACKUP_PATH"
```

Roles/permissions and external files need separate handling; validate access in
the restored environment. See [PostgreSQL backup documentation](https://www.postgresql.org/docs/15/app-pgdump.html).

## Remaining Phase 1 evidence

- [ ] Hosted GitHub Actions run passes on Python 3.12 / PostgreSQL 15.
- [ ] Railway service inventory, actual resource use, and service-level bill filled in.
- [ ] Production metrics and backlog captured for a defined window.
- [ ] Database and media backup configuration verified; missing coverage added.
- [ ] Real backup restored and application/media reads checked in isolation.

No production deploy, backup schedule, bucket permission, or billing setting has
been changed as part of the local implementation.
