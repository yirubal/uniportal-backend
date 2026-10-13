# UniPortal project reference

UniPortal serves study materials, quizzes, exam schedules and Telegram student
accounts for Unity University. The app is in its free adoption period; changes
must preserve current access. Monetization enforcement is deferred in
[improvemnts.md](improvemnts.md).

The backend stays a Django monolith with PostgreSQL, Django Admin, private R2
media and one durable worker. Railway Hobby is the current hosting plan. Actual
service memory, traffic, monthly usage and production backups remain unverified.

| Area | Responsibilities |
|---|---|
| `apps/accounts` | Students, subscription state transitions, notification intents |
| `apps/content` | Courses, resources, file inbox, upload validation and signed delivery |
| `apps/quiz` | Questions, selection, scoring, persisted simulations and attempts |
| `apps/exams` | Terms, sessions, validated atomic imports and reminder intents |
| `apps/bot` | Durable work claiming, Telegram handling, extraction and delivery |
| `apps/api/views` | HTTP feature modules: auth, students, catalog, resources, quiz, exams, subscriptions |

Views handle requests and serializers validate contracts. Concrete domain
functions in the owning app implement business rules. No generic repository,
service framework, broker, Redis or connection pool is introduced.

Telegram login verifies HMAC, requires an authentication timestamp within 24 hours
and allows at most 60 seconds of future clock skew. Seven-day access tokens are
retained until deployed frontend reauthentication is verified. Each protected
request loads an active student. Existing personal-record ownership and paper
access checks remain in place. General throttles use student IDs; low-frequency
auth/payment histories are shared in PostgreSQL.

Webhook requests authenticate using a required production secret and persist
updates before acknowledging. Channel documents are accepted only from the
configured numeric source channel. Inbox deduplication uses chat and message IDs.
The worker claims database records and executes one bounded subprocess at a time.
Notifications commit with their business transactions; external delivery is at
least once. Extraction is page/time bounded and paid AI chunks are reused.

Published resource links expire after 15 minutes and point directly to private
R2. Local storage uses signed streamed responses. File validation checks size,
extension and signatures; orphan audits are report only. Live R2 CORS and mobile
download behavior still need verification.

Quiz simulations persist their question snapshot and can be submitted once.
Pending essays are excluded from the gradable denominator. Performance summaries
aggregate in SQL. Lists retain their existing formats with opt-in pagination;
large lists require pagination explicitly. Exam imports validate before writing,
lock the term, and batch inserts/corrections using database uniqueness rules.

Production and Docker share `config/settings/production.py`. Containers build
static assets ahead of startup. Only the web release/pre-deploy role migrates;
web and worker restarts do not. Railway web uses `railway.json`; the worker must
select `railway-worker.json` and clear inherited web deployment overrides.
The web defaults to two sync Gunicorn workers; background concurrency stays one.
Production connections are reused for 60 seconds with health checks.

`/live/` checks the web process without querying the database. `/health/` executes
`SELECT 1`. `check_operations` reports queue counts, stale claims, disk use and
optional real-backup timestamps separately. Request/claim IDs support log
correlation; logs omit signed URLs, tokens and document bodies. Alert delivery
and production restore drills still require operational setup.

Run isolated checks with:

```bash
venv/bin/python manage.py check --settings=config.settings.test
venv/bin/python manage.py makemigrations --check --dry-run --settings=config.settings.test
venv/bin/python manage.py test --settings=config.settings.test --noinput
```

CI also runs PostgreSQL tests, a synthetic backup/restore and real OCR worker
recovery. See [README.md](README.md), [architecture](docs/ARCHITECTURE.md),
[Phase 5](docs/PHASE_5_DATABASE_API.md) for migration risks and benchmarks, and
[Phase 6](docs/PHASE_6_OPERATIONS.md) for production configuration and rollout.
