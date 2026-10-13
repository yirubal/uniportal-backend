# UniPortal Backend — Architecture

This document describes how the backend is put together today: the
processes that run, the Django apps and their models, and the main request
flows. For setup instructions see the [README](../README.md).

---

## 1. System overview

```mermaid
flowchart LR
    MA[Mini App] --> WEB[Django web and admin]
    TG[Telegram] --> WH[Webhook persistence]
    WH --> DB[(PostgreSQL work and application records)]
    WEB --> DB
    W[One durable worker] --> DB
    W --> T[Telegram delivery]
    W --> E[OCR and Gemini]
    W --> R[(Local media or R2)]
    WEB --> R
```

Webhook acceptance persists a unique update before returning success. Web and
admin requests queue work; `run_worker` executes one bounded child at a time.
Existing inbox and exam-upload records hold processing work. Telegram update,
notification, and AI records hold the remaining durable work. Failed jobs remain
visible, retries are bounded, and only stale claims are recovered. `run_bot` is
one-off recovery. See [Phase 3](PHASE_3_BACKGROUND_WORK.md) for deployment, limits,
and verification status.

---

## 2. Django apps

| App | Responsibility | Main models |
|---|---|---|
| `accounts` | Students, Telegram auth, subscriptions, payments, broadcasts | `Student`, `SubscriptionPlan`, `SubscriptionRequest`, `SiteSettings`, `BroadcastMessage` |
| `content` | Academic catalogue and downloadable materials | `Department`, `Course`, `CoursePlacement`, `Resource`, `FileInbox` |
| `quiz` | Question bank, past papers, scoring | `ExamPaper`, `Chapter`, `Question`, `QuizAttempt`, `QuizSimulation` |
| `exams` | Real exam schedule lookup from university PDFs | `ExamTerm`, `ExamSession`, `ExamScheduleEntry`, `StudentExam`, `ExamPDFUpload`, `ExamNotificationLog` |
| `bot` | Durable worker, Telegram handling, extraction and delivery | `TelegramUpdate`, `NotificationDelivery`, `QuestionExtraction` |
| `api` | All REST endpoints, auth middleware, permissions, throttles | — |

### Data model (simplified)

```mermaid
erDiagram
    Department ||--o{ CoursePlacement : has
    Course ||--o{ CoursePlacement : "placed by program/year/period"
    Course }o--o{ Resource : "has materials"
    FileInbox |o--o| Resource : "assigned to"

    Course ||--o{ Chapter : has
    Course ||--o{ ExamPaper : has
    Department ||--o{ ExamPaper : "exit exams"
    ExamPaper ||--o{ Question : contains
    Chapter ||--o{ Question : groups
    Student ||--o{ QuizAttempt : makes
    ExamPaper |o--o{ QuizAttempt : "attempted as"

    Student ||--o{ SubscriptionRequest : submits
    SubscriptionPlan ||--o{ SubscriptionRequest : for

    ExamTerm ||--o{ ExamSession : has
    ExamSession ||--o{ ExamScheduleEntry : has
    ExamSession ||--o{ StudentExam : has
    ExamTerm ||--o{ ExamPDFUpload : "parsed from"
```

---

## 3. Request flows

### 3.1 Authentication

```mermaid
sequenceDiagram
    participant MA as Mini App
    participant API as POST /api/auth/telegram/
    participant TG as Telegram API
    participant DB as Database

    MA->>API: init_data (signed by Telegram)
    API->>API: HMAC-SHA256 verify with bot token,<br/>reject if older than 24h
    opt TELEGRAM_OFFICIAL_CHANNEL_ID set
        API->>TG: getChatMember
        TG-->>API: member / not member
        API-->>MA: 403 CHANNEL_REQUIRED (if not member)
    end
    API->>DB: update_or_create Student(telegram_id)
    API-->>MA: JWT (student_id claim, 7 days) + profile
    Note over MA,API: later requests send Authorization: Bearer <JWT>;<br/>TelegramAuthMiddleware sets request.student
```

- Code: `apps/accounts/auth.py`, `apps/api/views.py` (`TelegramAuthView`),
  `apps/api/middleware.py`.
- There are no passwords. In `DEBUG` mode, `{"dev_mode": true}` skips the
  Telegram check for local testing.
- Permissions live in `apps/api/permissions.py`
  (`IsTelegramAuthenticated`, `IsPremium`).

### 3.2 Content ingestion

```mermaid
flowchart LR
    A[File posted in university channel] --> U[Webhook persists TelegramUpdate]
    U --> B[Worker runs handle_channel_post]
    B --> C[Download file<br/>→ FileInbox row]
    C --> Q[Worker claims FileInbox]
    Q --> D[process_inbox_item<br/>apps/bot/tasks.py]
    D --> E[extract_text<br/>pdfplumber → OCR fallback,<br/>images, docx]
    E --> F[FileInbox: processed<br/>+ extracted_text]
    F --> G{Admin review}
    G -- publish --> H[Resource<br/>linked to courses]
    G -- queue extraction --> AIQ[QuestionExtraction record]
    AIQ --> I[Worker calls Gemini<br/>apps/bot/extractor.py]
    I --> J[Inactive question drafts for review]
    X[Excel templates] -- import commands /<br/>admin import --> J
```

- Digital PDFs are parsed before OCR. Scanned PDFs above 5 MiB, PDFs above
  100 pages, empty results, and unsupported files require review; partial OCR
  is recorded explicitly. See Phase 3 for deadlines and retry semantics.
- `harvest_channel` back-fills historical channel files into `FileInbox`.

### 3.3 Resource downloads

Authenticated students receive expiring R2 GET URLs for published resources,
including resources classified as premium during the free adoption period.
Resource serialization returns a signed inline preview; download POST returns
an attachment URL, filename, and expiry. Django does not open R2 objects for
issuance. Legacy signed backend URLs redirect to R2; local development continues
to stream signed FileResponses. Counters measure issued download links.
See [Phase 4](PHASE_4_FILE_DELIVERY.md) for limits, storage settings, CORS,
frontend compatibility, and live checks.

### 3.4 Quizzes

- Questions are served by past paper (`/api/exams/{id}/questions/`), by
  chapter/topic (`/api/quiz/selective-practice/`), or by exit-exam topic
  (`/api/exit-exams/topics/questions/`).
- `POST /api/quiz/attempts/` scores the answers with
  `apps/quiz/engine.py:calculate_score`:
  - `mcq`, `true_false`, `fill_blank` are auto-graded.
  - `essay`, `matching` are marked pending and excluded from the score.
  - A per-topic breakdown is computed from `topic_tags`; topics under 50%
    are reported as weak. The pass mark is 50%.
- Simulations store the issued question snapshot in `QuizSimulation`, expose
  `X-Quiz-Simulation-ID`, count unanswered questions, and complete once.
- Attempts store the gradable denominator and pending count; weak topics use
  historical answer snapshots. See [Phase 2](PHASE_2_CORRECTNESS.md) for the
  submission contract and legacy-history fallback.
- Every attempt is stored as a `QuizAttempt` with detailed answers, which
  feed `/api/quiz/attempts/{id}/feedback/` and the premium-only
  `/api/students/me/performance/`.

### 3.5 Subscriptions (manual payment)

```mermaid
sequenceDiagram
    participant S as Student (Mini App)
    participant API as API
    participant A as Admin
    participant B as Bot

    S->>API: GET /api/subscription/plans/
    S->>API: POST /api/subscription/request/<br/>(plan, telebirr|cbe, payment reference)
    API->>API: create pending SubscriptionRequest (UNI- + 16 hex characters)
    API->>API: persist NotificationDelivery in transaction
    API->>B: worker delivers after commit
    A->>A: verify payment, "approve" admin action
    A->>API: approve_subscription_request (atomic locks)
    B->>S: confirmation message
```

- Only pending payments can be approved or rejected. Repeated approval does
  not extend access again; approved payments and renewals cannot be rejected.
- Payment delivery intents commit with the payment; the worker delivers with bounded retries.
- `Student.is_premium` = status is premium **and** expiry is in the future.
- `check_subscriptions` expires lapsed subscriptions; run it on a schedule.

### 3.6 Exam schedule lookup

1. Admin creates an `ExamTerm` and uploads schedule and attendance PDFs
   (`ExamPDFUpload`).
2. `apps/exams/parsers/` parse them; `apps/exams/services.py` builds
   `ExamSession` / `ExamScheduleEntry` / `StudentExam` rows, fuzzy-matching
   course names and codes.
3. Students search `GET /api/exams/lookup/?query=<student id or name>`
   against the active term.
4. `send_exam_notifications` queues countdown reminders for durable worker delivery.

---

## 4. API surface

All endpoints are under `/api/`. Full interactive docs: `/api/docs/`.

| Area | Endpoints |
|---|---|
| Auth | `POST auth/telegram/`, `POST telegram/webhook/` |
| Student | `GET/PATCH students/me/`, `GET students/me/watermark/`, `GET students/me/performance/` (premium) |
| Catalogue | `GET departments/`, `GET departments/{id}/courses/` |
| Resources | `GET courses/{id}/resources/`, `GET resources/{id}/`, `POST resources/{id}/download/`, `GET resources/{id}/download/file/{token}/` |
| Past papers | `GET exams/`, `GET exams/{id}/questions/` |
| Practice | `GET quiz/courses/{id}/chapters/`, `GET quiz/courses/{id}/topics/`, `POST quiz/selective-practice/` |
| Exit exam | `GET exit-exams/topics/`, `GET exit-exams/topics/questions/` |
| Attempts | `GET/POST quiz/attempts/`, `GET quiz/attempts/{id}/feedback/` |
| Exam schedule | `GET exams/active-term/`, `GET exams/lookup/` |
| Subscription | `GET subscription/plans/`, `GET/POST subscription/request/` |

Throttling (production defaults, relaxed in dev): anon 30/min, user
100/min, auth 10/min, subscription requests 5/min.

---

## 5. Configuration and environments

| Settings module | Used by | Database | Notes |
|---|---|---|---|
| `config.settings.dev` | `manage.py` default | `DATABASE_URL` or SQLite `db.sqlite3` | `DEBUG=True`, CORS open, relaxed throttles, browsable API |
| `config.settings.docker` | Dockerfile / compose | PostgreSQL service | Gunicorn, static files collected on start |
| `config.settings.prod` | Production hosting | PostgreSQL | HTTPS hardening, R2 storage |

Environment variables are read from `.env` (see `.env.example`).
Media goes to `media/` locally, or to Cloudflare R2 when `USE_S3=True`.

---

## 6. Scheduled / operational commands

| Command | Purpose |
|---|---|
| `check_subscriptions` | Expire premium subscriptions past their expiry |
| `repair_subscription_statuses` | Make premium state match approved requests |
| `send_exam_notifications` | Exam countdown messages to students |
| `process_exam_pdfs` | Process pending exam PDF uploads |
| `import_student_exams` | Import student exam rows from CSV |
| `run_worker` | Process durable work continuously with one child at a time |
| `run_bot` | One-off recovery of stale claims |
| `run_maintenance` | Daily subscription expiry, queued reminders, and bounded cleanup |
| `setup_webhook [--delete]` | Register or remove the Telegram webhook |
| `harvest_channel` | Back-fill historical channel files |
| `seed_data` | Seed departments, courses, plans, site settings |
| `import_course_with_chapters`, `import_questions_with_chapters`, `import_exit_exam_questions` | Bulk question imports from Excel |
| `cleanup_duplicate_inbox_files`, `repair_resource_files`, `fix_duplicate_courses` | Storage and data maintenance |

## Phase 5 query and import updates

Growing API lists offer opt-in pagination; legacy arrays are bounded, and attempt
history keeps its recent-20 contract. Resource relationships are prefetched,
question counts are annotated, question selection loads bounded IDs/full records,
and performance aggregates in SQL with bounded recent snapshots. Exam imports
validate before atomic batched writes and use database natural-key constraints.
Login/payment rate histories share a PostgreSQL-backed Django cache; general
student throttles remain process-local and approximate. See
[Phase 5](PHASE_5_DATABASE_API.md) for contracts, benchmarks, and rollout status.
