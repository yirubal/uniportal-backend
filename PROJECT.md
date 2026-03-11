# Unity University Student Portal — Backend

## What This Is
A Django + DRF backend powering the Unity University Telegram Mini App.
Students access organized study materials, practice quizzes, and exit exam
preparation through a Telegram Mini App. This backend handles all data,
file processing, authentication, and the Telegram bot.

---

## Tech Stack
- **Framework:** Django + Django REST Framework
- **Database:** PostgreSQL
- **File Storage:** Local filesystem (dev) → Cloudflare R2 (production)
- **File Processing:** pdfplumber, pytesseract, python-docx
- **Telegram Bot:** python-telegram-bot
- **Admin Panel:** Django Admin + django-unfold
- **Auth:** Telegram initData HMAC validation (no passwords)
- **Task Queue:** Django Q or Celery (for async file processing)

---

## Repository Structure
```
backend/
│
├── config/                  ← Django project settings
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/            ← Student profiles, Telegram auth
│   ├── content/             ← Departments, courses, resources
│   ├── quiz/                ← Questions, attempts, scoring
│   ├── bot/                 ← Telegram bot, file harvesting
│   └── api/                 ← All DRF endpoints
│
├── scripts/
│   └── harvest_history.py   ← One-time script to pull old channel files
│
├── requirements.txt
├── .env.example
├── manage.py
└── PROJECT.md               ← This file
```

---

## Django Apps — Responsibilities

### accounts/
- Student model (telegram_id, name, username, subscription_status, expiry_date)
- Telegram initData validation logic
- Subscription status checking
- Daily quota tracking (free tier limits)

### content/
- Department, Year, Semester, Course models
- Resource model (file, extracted_text, access_level, status)
- FileInbox model (harvested files pending admin triage)
- File processing pipeline (PDF/image → extracted text)

### quiz/
- Question model (text, options, correct answer, explanation)
- ExamPaper model (groups questions into a full past exam by year)
- QuizAttempt model (student, score, answers, timestamp)
- Scoring logic

### bot/
- Telegram bot process (runs alongside Django)
- Channel monitoring and file harvesting
- Student entry point (sends Mini App button)
- Notification sender (payment confirmed, new content alerts)

### api/
- All DRF ViewSets and serializers
- URL routing for all endpoints
- Permission classes (IsAuthenticated, IsPremium, FreeQuotaCheck)
- Download endpoint with logging

---

## Core Models Summary

```
Student
  telegram_id (unique)
  first_name, last_name, username
  subscription_status  [free | premium]
  subscription_expiry
  downloads_today
  last_download_reset

Department
  name
  code (e.g. CS, BA)

Course
  name
  department → FK
  year  [1-5]
  semester  [1 | 2]
  code

Resource
  title
  file  (FileField)
  file_type  [lecture_note | worksheet | past_exam | exit_exam]
  extracted_text  (TextField)
  access_level  [free | premium]
  status  [pending | published | rejected]
  course → FK
  telegram_message_id
  original_caption
  upload_date
  downloads_count

FileInbox
  file
  original_filename
  telegram_message_id
  telegram_caption
  posted_date
  processing_status  [unprocessed | processed | failed]
  extracted_text
  assigned_to → FK Resource (nullable)

Question
  text
  option_a, option_b, option_c, option_d
  correct_option  [a | b | c | d]
  explanation
  course → FK
  exam_paper → FK (nullable)
  difficulty  [easy | medium | hard]
  year_source  (e.g. "2022")
  access_level  [free | premium]

ExamPaper
  title
  course → FK
  exam_type  [final | exit]
  year
  duration_minutes
  total_questions
  access_level  [free | premium]

QuizAttempt
  student → FK
  course → FK (nullable)
  exam_paper → FK (nullable)
  score
  total_questions
  answers  (JSONField)
  completed_at
  mode  [practice | simulation | topic]
```

---

## Access Control Rules

| Action | Free User | Premium User |
|---|---|---|
| Browse resource titles | ✅ | ✅ |
| Download files | ❌ | ✅ |
| View file content | First page only | Full |
| Quiz questions/day | 5 max | Unlimited |
| Past exams (last 2 years) | ❌ | ✅ |
| Exit exam archive | ❌ | ✅ |
| Exit exam simulation | ❌ | ✅ |
| Performance tracker | ❌ | ✅ |

---

## Authentication Flow

```
Mini App sends Telegram initData (POST /api/auth/telegram/)
  → Django parses initData
  → Verifies HMAC-SHA256 signature using BOT_TOKEN
  → Checks timestamp not older than 24 hours
  → Extracts telegram_user_id
  → Creates or fetches Student record
  → Returns JWT token
  → All future requests use Authorization: Bearer <token>
```

---

## File Pipeline Flow

```
1. Bot receives file from Telegram channel
2. Bot downloads file to server
3. File saved to FileInbox with status=unprocessed
4. Processing task triggered:
   - PDF (digital) → pdfplumber
   - PDF (scanned) → pytesseract
   - Image → pytesseract
   - DOCX → python-docx
5. Extracted text saved to FileInbox
6. Status → processed
7. Admin sees file in Django Admin inbox
8. Admin triages: Tag & Publish / Reject
9. If published → Resource record created, file live for students
```

---

## Environment Variables (.env)
```
SECRET_KEY=
DEBUG=True
DATABASE_URL=postgresql://user:pass@localhost:5432/unity_uni
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
CLOUDFLARE_R2_ACCESS_KEY=
CLOUDFLARE_R2_SECRET_KEY=
CLOUDFLARE_R2_BUCKET=
CLOUDFLARE_R2_ENDPOINT=
OPENAI_API_KEY=        ← for question extraction AI parsing
ALLOWED_HOSTS=
CORS_ALLOWED_ORIGINS=
```

---

## Current Phase
**Phase 1 — Foundation**

## Progress
- [ ] Phase 1: Foundation
- [ ] Phase 2: File Pipeline & Bot
- [ ] Phase 3: API Layer
- [ ] Phase 4: Quiz System
- [ ] Phase 5: Access Control & Subscriptions
- [ ] Phase 6: Admin Polish & Launch Prep

---

## Key Decisions Log
- Django Admin used for admin panel (not custom React)
- python-telegram-bot for bot (not Telegraf — staying in Python)
- JWT tokens for API auth (not sessions — Mini App is stateless)
- AI parsing (OpenAI/Claude API) used to structure raw OCR text into MCQ JSON
- Manual Telebirr payment activation for now (no Chapa — no TIN yet)
- Files never sent directly to free users — server enforces access at API level
- Watermark overlay handled by frontend using student data from API