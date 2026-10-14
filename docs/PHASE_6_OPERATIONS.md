# Phase 6 — Code layout and production operation

Repository implementation: 2026-10-13. Railway rollout, actual proxy trust,
production backups, alert delivery, traffic sizing and cost comparison remain
unverified. Student access rules and payment approval rules are preserved.

## Code responsibilities

`apps/api/views.py` is now a package with explicit `auth`, `students`, `catalog`,
`resources`, `quiz`, `exams` and `subscriptions` modules. The package reexports
existing view classes and the existing JWT helper/download constants. URLs and
response contracts remain stable. Serializers and concrete domain functions stay
in their existing owning apps. No generic service/repository abstraction is added.

Earlier phases removed caller-stack payment authorization and duplicated inline
extraction. Payment changes still use locked, explicit state transitions; only
pending payments can be rejected. Telegram, notifications, PDF/OCR and AI work
run through the durable worker.

## Production settings

`prod.py` and `docker.py` import the shared `production.py`. The production entry
point rejects DEBUG=True; containers allow an explicit local DEBUG=True opt-in.
`.env.example` now represents local development and must not be copied unchanged
to Railway.

With DEBUG=False, configure:

| Variable | Required action |
|---|---|
| `SECRET_KEY` | Random value of at least 50 characters; development keys are rejected. Keep the existing strong key unless intentionally rotating tokens/signed links. |
| `DATABASE_URL` | Existing Railway PostgreSQL service reference; SQLite is rejected. |
| `ALLOWED_HOSTS` | Explicit API hostname(s), `healthcheck.railway.app`, and loopback hosts for Docker health checks. No wildcard. |
| `CORS_ALLOWED_ORIGINS` | Deployed frontend HTTPS origins. |
| `CSRF_TRUSTED_ORIGINS` | HTTPS origins used for admin requests. |
| `TELEGRAM_BOT_TOKEN` | Existing real bot token. |
| `TELEGRAM_WEBHOOK_SECRET` | Required, 1–256 Telegram-compatible letters/digits/underscore/hyphen. Register the identical value with Telegram before routing traffic to the new deployment. |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS webhook endpoint used by `setup_webhook`; no production project URL is hardcoded. |
| `TELEGRAM_CHANNEL_ID` | Required numeric source channel ID, e.g. `-100…`. This differs from the optional official membership channel. |
| `USE_S3` | Defaults to true in production; keep true for private R2. Local storage requires an explicit override and a shared persistent media volume. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | Existing private bucket credentials and name. |
| `R2_ACCOUNT_ID` or `R2_ENDPOINT_URL` | Existing account/endpoint. AWS-compatible aliases remain supported. |
| `GEMINI_API_KEY` | Needed for AI extraction; `GOOGLE_API_KEY` remains an alias. Optional features do not block startup. |
| `GUNICORN_WORKERS` | Defaults to 2 sync workers. Choose from actual memory/latency measurements. |
| `DB_CONN_MAX_AGE` | Defaults to 60 seconds for both production entry points, with connection health checks. |

Secure session/CSRF cookies are mandatory with DEBUG=False, including Docker.
WhiteNoise uses built, compressed manifest assets; runtime finder/autorefresh is
disabled. Private storage still signs links and never uses a public custom domain.

`TRUST_PROXY_HTTPS=False` is the default. Set true only after confirming the
Railway ingress overwrites `X-Forwarded-Proto` and the application is not publicly
reachable around that trusted ingress. Verify HTTPS admin login and POSTs, then
set `SECURE_SSL_REDIRECT=True` and enable HSTS after checking redirect/health-check
behavior. HSTS starts at zero to avoid asserting an unverified proxy configuration.
`THROTTLE_NUM_PROXIES` independently controls trusted forwarded IP selection;
verify the actual chain before changing it. Zero ignores forwarded IP headers,
which can group unauthenticated users behind the Railway proxy.

Production deployment security checks:

```bash
python manage.py check --deploy --tag security --fail-level WARNING
```

These intentionally report unconfigured TLS/HSTS until the rollout settings are
verified. A synthetic production configuration passed locally. The full schema
deployment check still reports existing OpenAPI typing/operation-ID warnings;
schema completeness is not asserted here. API docs/schema URLs are now actually
limited to DEBUG, matching their previous documented intent.

Railway documents the health-check host and config precedence in its
[health-check guide](https://docs.railway.com/deployments/healthchecks) and
[configuration reference](https://docs.railway.com/config-as-code/reference).

## Authentication and source controls

Telegram login requires a decimal positive `auth_date`, rejects timestamps older
than 24 hours and those more than 60 seconds in the future, rejects duplicate
fields/malformed hashes, and validates the signed user ID and profile field types.
HMAC validation remains required. The existing signature compatibility is retained.

Seven-day access tokens are retained. The adjacent omega frontend clears its
stored token on HTTP 401, while backend permission failures can return 403; the
deployed frontend and recovery flow are not confirmed. Shortening tokens before
verifying that behavior could strand students. Coordinate expired-token handling
and fresh Telegram reauthentication before a later lifetime change. No refresh
endpoint is introduced and refresh tokens are not returned to students.

Production requires the webhook secret. Header comparison is constant time.
Unconfigured/other source channel posts are acknowledged without storing work;
the worker checks the configured source again before downloading. Student bot
messages remain accepted. Only one ingestion source is configured today; inbox
deduplication already includes `(chat_id, message_id)` for future multiple sources.

## Release and restart procedure

Docker collects static assets while building, using `config.settings.build`,
without database/R2/bot credentials. Build settings reject use outside
`collectstatic`. Gunicorn and the worker never migrate or collect static at startup.
The Procfile has an explicit release role for platforms that support it; Railway
uses the explicit pre-deploy configuration instead.

Before pushing a release that Railway will auto-deploy, confirm each service’s
config path and remove stale start/health-check/migration overrides:

| Railway service | Config-file path | Role |
|---|---|---|
| Web | `/railway.json` | Docker build, one migration pre-deploy command, Gunicorn, `/health/` readiness |
| Worker | `/railway-worker.json` | Docker build, `run_worker`, one replica, no pre-deploy migrations or HTTP check |
| Daily maintenance | `/railway-maintenance.json` | `run_maintenance`, daily 03:00 UTC / 06:00 EAT, no restart loop or HTTP check |

Do not let worker/cron services inherit the root web config: config-as-code takes
precedence over service UI commands. A pre-deploy command executes per deployment;
keep exactly one migration-owning web service and serialize releases. Separate
concurrent web releases are not protected by a new global migration lock.
Deploy the web/schema before the matching worker, then run one test upload,
notification and quiz submission. Scheduled services should use the same image
and required environment, not run continuously as additional web servers.

Compose is explicitly a local setup. Its one-shot `release` service completes
migrations before web readiness; built static assets are not hidden by a volume.
For later local releases, recreate the completed release container:

```bash
docker compose up --build --force-recreate release
docker compose up --build -d django worker
```

Back up the actual database and private media before migrations. Read Phase 5’s
roster conflict preflight and concurrent-index retry instructions. Application
rollback does not undo data migrations, reconstruct deduplicated rows, or restore
formatted values. Stop workers and writes before restoring a matched database
and media backup; restore to an isolated target first and prove it before switching.
The synthetic restore drill is useful evidence, not proof of real backups.

## Health, logs and alerts

`/live/` returns process liveness without a database query. `/health/` executes
`SELECT 1` and returns 503 on a database error without exposing connection details.
Neither endpoint inspects queue sizes or reports backup success.

Requests accept a valid UUID `X-Request-ID` or generate a new one, return it and
log method, route name, status and duration. Error logs record exception type and
code locations without exception text/student bodies. Worker logs use job kind,
record ID and UUID claim ID. Raw Gunicorn access logging and HTTP-client INFO
logging are disabled because URLs can include bot credentials or signed links.
Production Django request logging is replaced by the sanitized request middleware.
Log to console with Railway retention; no unbounded ephemeral log file is created.

Run the read-only command separately from web health checks:

```bash
python manage.py check_operations
python manage.py check_operations --backup-status-file /shared/backup-status.json
```

The JSON report contains counts only. Default thresholds fail the command for any
stale claim, any failed work awaiting review, more than 1,000 pending jobs, work
overdue by 15 minutes, or local temporary/media disk use at 85%. Future scheduled
retries are not overdue. Tune thresholds after observing broadcasts/imports and
rate-limit delays; historical failed jobs require review or an explicit tolerated
`--max-failed` threshold. Five aggregate queue queries bound the report.

When supplied, the backup status file must contain BOTH timezone-aware ISO
timestamps, `database_completed_at` and `media_completed_at`, written only after
actual archival success. Missing/invalid/future timestamps or age over 26 hours
fail the command. No backup file means `unverified`; the command can report other
checks healthy without claiming backups are verified. A timestamp does not prove
restore integrity, and ephemeral Railway files do not survive deployments.

Connect the command’s nonzero exit to an existing alert runner/operator notification
channel, using a durable/shared status location supplied by the actual backup
system. Configure API alerts from sanitized request logs, starting with 5xx over
1% for five minutes with at least 100 requests, or five consecutive readiness
failures. Review queue growth and disk alerts against observed workload. An alert
receiver and real-backup writer have NOT been configured or contacted in this work.
Do not add a paid monitoring service just for this phase; alert wiring remains an
explicit rollout item.

## Dependencies and verification

An isolated temporary `pip-audit 2.10.1` installation reviewed installed packages.
After Django was patched, it reported 93 advisory matches (including duplicate
records) across ten other packages. Targeted updates cover Django 6.0.9,
DRF 3.17.2, PyJWT 2.15.0, cryptography 50.0.2, pdfplumber 0.11.10 with
pdfminer.six 20260107/pypdfium2 5.14.0, Pillow 12.3.0, AnyIO 4.14.2,
IDNA 3.15, lxml 6.1.0, sqlparse 0.6.0 and urllib3 2.8.0.

Wand was removed only after the maintained pdfplumber dependency chain no longer
required it. No source uses ImageMagick or libmagic; those runtime packages were
removed too. Poppler and Tesseract remain for the explicit bounded OCR path.
Other direct/transitive pins were retained. The final installed-package audit
reported no known matches in 65 packages; this excludes OS/bundled native-library
advisories and undisclosed issues. [Audit inventory](PHASE_6_DEPENDENCY_AUDIT.json).

Primary release evidence: [Django security release](https://www.djangoproject.com/weblog/2026/oct/06/security-releases/),
[DRF notes](https://github.com/encode/django-rest-framework/blob/main/docs/community/release-notes.md),
[PDF parser notes](https://github.com/jsvine/pdfplumber/blob/stable/CHANGELOG.md),
[PyJWT notes](https://pyjwt.readthedocs.io/en/2.15.0/changelog.html),
[cryptography notes](https://cryptography.io/en/stable/changelog/),
[Pillow notes](https://pillow.readthedocs.io/en/stable/releasenotes/).

Local verification with the revised pins: 182 PostgreSQL tests passed; SQLite
passed 174 with eight PostgreSQL-only skips. System/migration checks, static asset
collection, worker crash recovery and synthetic database/media restore passed.
The host lacks Tesseract; container verification now covers real OCR. Hosted CI
execution remains unverified. Production web verification is recorded below;
Compose and Railway configuration validation passed independently.

### Docker verification — 2026-10-14

After enabling Docker Desktop WSL integration and resolving local Docker DNS,
the current Dockerfile built successfully without production credentials.
The image installed the Python 3.12 dependency pins and prepared WhiteNoise
manifest assets: 199 files copied and 569 post-processed. Inside that exact image,
with external networking disabled:

- `pip check` reported no broken requirements.
- The packaged test suite ran 182 tests: 174 passed, eight PostgreSQL-only skips.
- `scripts/check_container_extraction.py` loaded native PDFium and successfully
  extracted the synthetic marker from both an image and a scanned PDF using
  real Tesseract and Poppler. Temporary files were cleaned afterward.

Reproduce with:

```bash
docker build --tag uniportal-verification:local .
docker run --rm --network none uniportal-verification:local python -m pip check
docker run --rm --network none \
  -e DJANGO_SETTINGS_MODULE=config.settings.test -e READ_DOT_ENV=False \
  uniportal-verification:local python manage.py test --noinput
docker run --rm --network none \
  -e DJANGO_SETTINGS_MODULE=config.settings.test -e READ_DOT_ENV=False \
  uniportal-verification:local python scripts/check_container_extraction.py
```

The `container` job in `.github/workflows/checks.yml` repeats these checks on
push/PR. Its hosted execution is not yet verified. These results verify image
packaging and synthetic extraction; live worker deployment, production media,
proxy behavior, representative OCR resource use and actual backups remain
separate rollout checks. No Railway services or production data were changed.

## Sizing evidence and remaining rollout checks

### Production web recovery — 2026-10-15

The owner authorized retaining one record per duplicate exam identity. Production
was audited with the same normalization rules as `exams.0007`; the remaining
conflict was rows 3889/3893. Both were archived in private R2 and read back with
SHA-256 verification before row 3893 was deleted transactionally, retaining 3889.
Row 5361 had already been removed before this cleanup; row 5360 remained.
The final StudentExam and ExamScheduleEntry audits found no duplicate identities.
The source PDFs themselves contain the conflicting details; keeping the oldest
record followed the disclosed cleanup policy and does not verify the academic details.

Affected-row backup (not a full database backup):
`operations/backups/exam-duplicate-cleanup/2026-10-14T22-12-29Z-87c21645ca7e4e3cb277d0f1c418493b.json`.

The first retry applied `exams.0007` and `content.0017`, then failed readiness
because `healthcheck.railway.app` was absent from ALLOWED_HOSTS. That exact host
was appended to the existing web-service variable. Redeploying existing commit
`a7df036c58facc71f84d791d9bb8be59f41fc585` then succeeded, deployment
`2558aa01-e999-41ef-ad7b-5f4f2eaac1d1`. Live `/health/`, `/live/` and
`/api/departments/` returned HTTP 200; readiness confirmed a database connection.

Web/schema deployment is now verified. The project inspection showed only web
and PostgreSQL services; durable worker and daily maintenance rollout, broader
student-flow tests, TLS/proxy verification, scheduled full backups/restore,
alert delivery and production sizing remain pending.

[Synthetic web comparison](PHASE_6_WEB_BENCHMARK.json) runs one, two and four sync
workers against a disposable PostgreSQL database: 50 departments, 30 resources,
1,000 questions and 500 attempts. Four local clients issue 60 requests after 12
warmups, rotating catalogue/resources/history/performance endpoints. Linux PSS
adds the master and workers without double-counting shared pages; it excludes
PostgreSQL and the separate extraction worker. This is one noisy local run, not
a load test or a production SLO/cost baseline. Tail latency varies substantially.

| Web workers | Web PSS (MiB) | p50 (ms) | p95 (ms) | Requests/s |
|---|---:|---:|---:|---:|
| 1 | 94.34 | 958.31 | 1510.69 | 3.71 |
| 2 | 165.93 | 145.28 | 1783.79 | 5.83 |
| 4 | 297.65 | 47.14 | 2069.14 | 7.61 |

Two remains the shared default, aligning with the existing Railway Procfile and
reducing the Docker default from four. Background concurrency stays one. Pooling
and additional replicas are deferred: measure peak connections first, including
web workers, the worker parent/child, maintenance and release commands.

For production, record p50/p95 API latency, 5xx rate, per-role peak memory/CPU,
oldest pending work, peak DB connections, database/media storage, and the actual
Railway/R2/AI bill over comparable periods. Increase workers only when queueing is
the bottleneck and memory has headroom. OCR/import memory must be measured
separately with representative files; Hobby plan maximums are not allocations.
Phase 1 production measurements were never supplied, so no verified cost saving
or before/after production latency claim is made.

Pending: confirm service config paths and migration ordering; verify trusted
proxy scheme/IP handling, admin HTTPS, health checks, Telegram relaunch after token
expiry, real backups/restore, scheduled maintenance, alert receiver and real
R2/mobile delivery. Keep monetization deferred while completing those checks.
