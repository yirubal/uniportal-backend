# Phase 2 — Quiz and payment correctness

Implemented and verified locally on 2026-10-08. Production deployment and
frontend verification are pending. No new paid-access restrictions were added.
The existing legacy gates remain inventoried in the Phase 1 baseline.

## Quiz requests and scoring

Question selection and quiz submission now use focused DRF input serializers.
Invalid modes, malformed answers, duplicate or unknown question IDs, invalid
options, and inconsistent paper/course/department contexts return HTTP 400.
Selective submissions must match their supplied course and topics.

Requests are bounded to 500 questions/answers; selective practice allows up to
100 questions and 50 topic selections. These are processing limits, not daily
allowances. Papers exceeding 500 questions cannot start a simulation and need
editorial review. Large-bank selection efficiency remains Phase 5 work.

New attempts store `gradable_total` and `pending_count`. Percentages divide the
score by auto-gradable questions, including unanswered auto-gradable questions.
Essay and matching questions remain pending for review and are excluded from
that denominator. There is no new manual grading workflow in this phase.
Submission, feedback, history, pass status, and performance use the same
percentage. Per-paper averages now average percentages instead of raw scores.
Weak topics come from saved answer snapshots, so later bank edits/deletions do
not rewrite historical topic results.

Migration 0010 backfills denominators only when stored feedback covers the full
recorded attempt and supplies enough grading information. Incomplete or unknown
legacy snapshots retain their original total-question denominator and expose
`gradable_total: null`; missing historical data is not guessed. Previously
omitted simulation questions cannot be reconstructed retrospectively.

## Simulation contract

`GET /api/exams/<id>/questions/?mode=simulation` still returns a question array.
It also returns `X-Quiz-Simulation-ID`, exposed through CORS. The backend stores
the issued questions and their grading data in a small `QuizSimulation` record.
Refreshing resumes the student's unfinished simulation for that paper. Once
completed or expired, opening the paper starts another simulation.

The frontend should retain the header and include it on submission:

```json
{
  "mode": "simulation",
  "exam_paper_id": 123,
  "simulation_id": "UUID returned in X-Quiz-Simulation-ID",
  "answers": [{"question_id": 456, "selected_option": "a"}]
}
```

Omitted answers count as unanswered; an empty answer array is valid for a started
simulation. Scoring uses the issued snapshot even if questions are subsequently
edited or deleted. Submission locks the simulation and completes it once.
Repeated completion returns HTTP 409 without creating another attempt. Unknown,
foreign, expired, or unissued simulations/questions return HTTP 400.

For compatibility, a submission without `simulation_id` uses the student's
latest simulation for the supplied paper. Sending the ID is necessary to
unambiguously distinguish stale submissions after a new simulation has started.
A simulation must have been opened before submitting. Frontend response handling
for these errors and the header still needs verification in its repository.

Sessions expire after 24 hours; this is a validity window, not enforcement of the
paper's exam timer. Retention/cleanup is deferred to scheduled maintenance.
Practice and selective attempts score the submitted selection; issued-set
tracking applies to simulations only.

## Payment transitions

Approval locks the student and payment request in one transaction. Only pending
requests can activate access. Repeated or concurrent approval grants access
once; renewal extends the existing valid expiry once. Failed saves roll back
both payment and student state. Request creation also serializes pending-request
creation for the student, alongside the existing database uniqueness constraint.

The owner confirmed: **reject pending payments only**. Bulk rejection and admin
detail edits preserve approved payments, including renewals, and their granted
access. Correcting an approved payment requires a separately designed, explicit
operation; this phase does not introduce one.

Creation, approval, and rejection notifications run after commit. Notification
exceptions cannot roll back committed state. Delivery is still synchronous and
has no durable retry guarantee; moving it to a worker remains Phase 3 work.
New references use `UNI-` followed by 16 hexadecimal characters within the
existing 20-character field, avoiding a shrinking five-digit namespace. Payment
responses preserve the recorded amount even if plan pricing changes later.

## Downloads and publishing

Download counters use database increments within a transaction. The student's
daily reset is serialized with their increment, preventing lost updates and
repeated resets under concurrent requests. Counters represent **issued download
links**, not verified completed transfers. File delivery remains unchanged until
Phase 4.

Publishing an inbox item no longer assumes `Course(pk=1)`. It creates a pending,
unassigned resource for administrator classification, preserves the shared
stored file, and locks the inbox to avoid duplicate publication.

## Verification and rollout

- PostgreSQL 18.6: all 113 tests passed, including competing approval/rejection,
  duplicate simulation completion, and download increments across connections.
- SQLite: 113 tests ran; 108 passed and five PostgreSQL-specific tests skipped.
- Django system checks and migration drift checks passed.
- Synthetic database/media backup and restore passed with the new schema;
  production backup arrangements remain unverified.

Deploy the code and apply migrations before serving requests with the new code:

```bash
python manage.py migrate
```

Migrations 0009 and 0010 add the simulation table and attempt counters and backfill
eligible history in batches of 500. Back up the production database first and
allow time for a scan of historical attempts. Production migration timing has
not been measured. Follow the existing Railway release process, restart web
processes after migration, and verify simulation issuance/submission, mixed
question feedback, and pending-only admin rejection. Verify the frontend sends
the simulation ID and handles 400/409 responses before considering rollout done.
Do not reverse migrations while new code is running; reversing removes stored
simulation data and counter fields.
