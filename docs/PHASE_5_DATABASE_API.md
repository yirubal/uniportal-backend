# Phase 5 — Database and API efficiency

Implemented 2026-10-13. Repository checks pass. Frontend pagination adoption,
trusted-proxy configuration, hosted CI, and production measurements remain open.

## Query changes

Resource serializers now iterate prefetched course objects. Course codes and
names no longer issue two SQL queries per resource. Paper lists load departments
and courses together and annotate active-question counts once. Chapter lists
annotate counts; history loads nested paper relationships and counts in its
bounded query, omitting unused answer/topic JSON from history rows. Related chapter data is loaded with selected questions.

Question selection filters exact topic strings in the database. PostgreSQL uses
JSONB containment; SQLite uses JSON1 with bound parameters. A tag `Loops` does
not match `Nested Loops`. Multiple selected topics mean any matching tag, with
one question returned once. Existing selective ordering is preserved.

Random practice/topic selection samples lightweight IDs across the entire
eligible bank, then loads only the selected questions and chapters. It no longer
loads the bank or biases selection toward the first 500 records. SQL still
examines eligible IDs to randomize them; this is bounded application memory,
not constant database work. Requests retain the 500-question ceiling and selective
practice's 100-question ceiling. The old five-question per-request clamp is
removed; free students' requested selection size is respected. Limits bound work
per request during adoption. Existing paper-level permissions are unchanged.

The course-topic API still interprets the first topic tag as a legacy chapter
label. The chapter API uses the actual `Chapter` foreign key. These semantics
are kept explicit; this phase does not merge those representations.
Topic catalogues stream tag metadata rather than loading full questions.

Performance summaries use SQL for all-history count/average/best and per-paper
averages. Only the latest 30 score/time rows and latest 20 answer snapshots are
read; snapshots stream one at a time. Query count is four, independent of history
length. Historical topics still use saved feedback, never today's question bank.
Individual percentages now round half-up to one decimal across scoring, saved
attempts, topic results, and SQL summaries: e.g. 1/400 is 0.3%, rather than the
old Python half-even 0.2%. Gradable denominators and legacy fallback stay intact.

## Pagination rollout

Existing array consumers were inspected read-only in the neighboring frontend
repositories. Their live deployment was not identified or modified.

For departments, department courses, course resources, papers, attempt history,
and exit-topic counts, opt in with `page` or `page_size`:

```text
GET /api/courses/12/resources/?page=1&page_size=50
```

```json
{"count": 123, "next": "https://...page=2", "previous": null, "results": []}
```

Default paged size is 50, maximum 200. Invalid sizes return 400; invalid/out-of-range
pages use DRF's 404 response. Ordering includes a primary-key tie breaker so
unchanged datasets have stable page boundaries. Changes during offset pagination
can move rows; no snapshot/cursor framework is added.

Without pagination parameters, ordinary lists retain their array shape up to
500 entries. Larger lists return an explicit 400 asking the client to paginate,
rather than silently showing an incomplete catalogue or loading unlimited data.
Legacy attempt history keeps its existing latest-20 array; paged history can
retrieve older attempts. Chapter responses retain their outer course fields and
`chapters` array; paged requests add `next`/`previous` and report `total_chapters`.

The frontend must follow `next`, append results, and handle loading/end states
before deploying against catalogues above the legacy ceiling. Filters are retained
in generated page links. Numeric catalogue filters and bounded resource searches
now return client errors for malformed inputs. The frontend's legacy `type=exit`
filter is retained. Free resource delivery from Phase 4
continues to use expiring URLs; fetch fresh details/download links when needed.

## Exam import correctness

Schedule and attendance PDF imports validate the parsed dataset before creating
terms, sessions, schedule entries, or roster rows. CSV imports validate the entire
file first, including required columns and the last row. Imports allow at most
20000 rows and 200 distinct sessions; writes/read batches are bounded to 100 rows.
Names/IDs/codes/rooms have model field-length checks; empty required fields and
invalid time ranges fail. Rows belonging to different terms or a wrongly selected
upload term are refused.

Imports lock the term and commit their business rows plus upload result together.
Duplicate identities with conflicting details within one input fail the import.
Identical re-imports create/update nothing. Matching identities update descriptive
details and record both created/updated counts. Unmentioned rows are preserved.
Session time conflicts require an explicit admin correction before re-import;
imports cannot silently move every exam attached to that session. Exam start date
comes from the retained sessions' earliest date.

Database identities are:

- Schedule entry: session + course code.
- Roster with student ID: session + student ID + course code + room.
- Roster without student ID: session + exact student name + course code + room.

IDs are trimmed/uppercased, and course codes use the existing canonical format
(e.g. `acct101` becomes `ACCT 101`). Matching IDs can correct names/departments.
Missing-ID name changes, room/course changes, and removals require explicit
review of the old record because those change identity. Resolve ambiguous
homonyms/missing course codes before import; blank course codes are rejected.

Migration exams 0007 normalizes existing strings, retains the lowest ID for
exact duplicate payloads, then adds uniqueness constraints. Conflicting payloads
at one identity **abort the migration with record IDs**; they are not guessed or
silently deleted. Normalization and duplicate removal are atomic. This needs a
production backup and conflict review before release; reversing the migration
does not restore removed exact duplicates or original formatting.

## Throttling and caching

General authenticated request throttles now use student ID, not DRF's anonymous
`request.user`/shared campus IP. Student requests bypass the anonymous throttle.
General availability limits remain approximate and process-local.

Login and subscription throttles share a dedicated Django database-cache table
across web workers. This uses the existing PostgreSQL service, with no additional
cache service. Only these lower-frequency endpoints incur database cache writes.
DRF histories remain non-atomic and approximate under simultaneous requests;
payment state/uniqueness is enforced separately by transactions and constraints.
Expired throttle rows are removed by daily maintenance.
[DRF throttle behavior](https://www.django-rest-framework.org/api-guide/throttling/).

`THROTTLE_NUM_PROXIES=0` ignores forwarded headers. **Before production rollout,
verify the actual trusted Railway/proxy chain and set its count explicitly.**
If `REMOTE_ADDR` is a shared proxy, leaving zero groups anonymous login traffic
under that proxy's rate limit. Setting a guessed count can trust spoofed headers.
No unverified proxy count is automatically selected.

Catalogue caching was deliberately not added: direct catalogue query counts are
now small, and production repeat/hit-rate data has not justified invalidation
complexity. The shared throttle cache is independent of catalogue caching.

## Measured indexes and local results

A disposable PostgreSQL 18.6 database contained 20000 synthetic questions and
10000 attempts (5000 for the focus student). EXPLAIN ANALYZE used normal planner
settings; no index-use forcing was applied. Full plans are in
[PHASE_5_QUERY_PLANS.json](PHASE_5_QUERY_PLANS.json).

| Check | Before | After |
|---|---:|---:|
| Serialize 3 prefetched resources | 8 queries | 2 queries |
| Serialize 30 prefetched resources | 62 queries | 2 queries |
| Exact rare-tag lookup, 200 matches | 6.547 ms | 0.379 ms |
| Latest 30 attempt IDs | 1.597 ms | 0.053 ms |
| Full-object summary kernel / complete SQL summary | 210.012 ms | 23.411 ms |

The summary timing is a three-run local median. Its baseline kernel loads all
attempt objects and computes average/best; the new timing includes the complete
summary. It demonstrates the load reduction, rather than an identical production
request benchmark. Dataset, warm-cache conditions, and hardware affect timings.
No Railway latency or bill improvement is claimed.

Two indexes were justified: active-question JSONB GIN (`jsonb_path_ops`) for exact
tag containment, and student/completed-time/ID ordering for recent attempts.
Plans use a GIN bitmap scan and recent-history index-only scan. The redundant
single-column attempt-student FK index is removed after the composite is added.
The GIN index is PostgreSQL-only and built concurrently; SQLite uses JSON1 without
that index. No unrelated indexes or separate caching service were introduced.

## Validation and rollout

- Full PostgreSQL suite: 164 passed; the subsequently added competing-import test
  also passed (165 distinct cases verified).
- SQLite: 165 tests ran; 157 passed, eight PostgreSQL-specific tests skipped.
- Tests cover query-count bounds, SQL JSON matching, percentage ties, page
  contracts, history limits, shared throttle histories, rollback, canonical
  identities, exact-duplicate migration, conflicting-data refusal, and competing
  imports.
- System checks, migration drift, whitespace checks, and synthetic backup/media
  restore passed. Hosted CI and production integration remain unverified.

Apply api 0001, exams 0007, and quiz 0011 before starting new code. Review/back up
existing exam data and coordinate frontend pagination/proxy configuration first.
The recent-history index build and constraint scan need a suitable release window;
production migration duration is unmeasured. Quiz 0011 is non-atomic to build the
GIN index concurrently: if it fails partway, inspect completed operations and any
invalid index before retrying. Stop new code before reversing schema changes.
Validate representative imports/API pages in staging, then compare real request
latency, query plans, worker memory, and Railway usage against Phase 1.
