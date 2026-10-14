# Phase 4 — File delivery and memory costs

Implemented 2026-10-13. The owner confirms R2 public access is disabled. Live
bucket configuration, browser CORS, Telegram mobile downloads, and Railway usage
have not been independently inspected. Phase 3's worker/scheduler rollout and
hosted OCR smoke check also remain unverified.

## Delivery contract

`POST /api/resources/<id>/download/` retains `{url, filename, expires_in}`.
With S3/R2 storage, `url` is now a 15-minute signed GET on the S3 API endpoint.
Django signs the request locally and does not open or transfer the object.
Download counters still count issued links, including repeats, not completed
transfers. A missing file reference returns 404 before incrementing counters;
object existence is checked by R2 at download time, avoiding per-link HEAD calls.

Resource serializers retain `file_url`, now an expiring inline preview URL,
and add `file_url_expires_in`. Unauthenticated serializer contexts and unpublished
resources do not expose a URL. Filename and inferred content type are included
as signed response parameters for R2. Verify their actual returned headers on
representative files during rollout. Unicode filenames use the standard Django
Content-Disposition formatter.

Published resources are free during adoption: resource API `access_level`
reports effective `free` access and `is_locked` is false for authenticated
students. Stored resource classifications remain available to administrators.
The old resource-download premium gate is removed. This change is limited to
resource delivery; quiz/performance monetization readiness remains deferred.
Existing bearer links remain usable by their holders until expiration; changing
a resource's status cannot immediately revoke an already-issued R2 signature.

The legacy Django signed-download route remains supported: it validates the
signature, age, current publication status, and stored filename, then redirects
R2 requests to storage. HEAD requests receive a HEAD signature. Local development
still streams a FileResponse, with signed inline previews and attachment
downloads. Neither resource previews nor legacy link retrieval increment
issuance counters.

Both R2 settings paths now use Signature V4, signed storage URLs, no public ACL,
and no unsigned custom-domain URL fallback. This also covers admin file widgets.
The explicit delivery helper signs through the authenticated SDK connection even
if old public-domain/query-string settings are accidentally retained.
Presigned URLs use the S3 endpoint, not a custom domain.
[Cloudflare presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).

## Frontend and CORS rollout

Read-only inspection found two neighboring frontend repositories. The original
`uniportal-frontend` viewer has a dummy download handler; the `-omega` viewer
calls Telegram's download API with the returned URL and filename, with a browser
fallback. Neither repository was changed or established as the live deployment.
The known resource premium check reads the API access level, which now reports
free for published resources. Verify the actual deployed build and any additional
`canDownload` checks rather than assuming end-to-end adoption access is complete.

Fetch a fresh download URL for each click. Refresh resource details before using
a cached preview after 15 minutes; do not persist signed URLs as permanent file
identities. Retry expired preview/download links by calling the authenticated API
again. The existing JSON response shapes remain compatible apart from the added
preview expiry field and intentional resource-access behavior.

Keep the bucket private. Configure bucket CORS for the actual frontend origins
before deployment when previews use browser fetch. For example, replace the
placeholder below with the deployed origin:

```json
[{
  "AllowedOrigins": ["https://YOUR-FRONTEND-DOMAIN"],
  "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["Range", "If-Range"],
  "ExposeHeaders": ["Content-Disposition", "Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag"],
  "MaxAgeSeconds": 3600
}]
```

Include additional request headers only if the frontend sends them. Signed GET
URLs authorize GET; code performing a separate HEAD request needs a HEAD link.
An expired presigned response can lack CORS headers, so JavaScript may see a
network/CORS failure rather than readable 403 details.
[Cloudflare CORS documentation](https://developers.cloudflare.com/r2/buckets/cors/).
No live CORS policy or bucket visibility was changed by this work.

## Upload and extraction bounds

- Upload memory threshold: **1 MiB**, then disk-backed Django temporary files.
  R2-backed file reads also spool after 1 MiB in production settings.
- Document limit: **100 MiB per file**, configurable with
  `MAX_DOCUMENT_UPLOAD_BYTES`.
- Exam PDF limit: **20 MiB per file**, configurable with
  `MAX_EXAM_PDF_UPLOAD_BYTES`.
- Non-file request data threshold: **2 MiB**; at most **20 uploaded files** per
  multipart request. File payloads are separate from the non-file threshold.

Model/admin upload validation checks non-empty size, extension, basic file
signatures, and Office container markers without trusting supplied MIME labels.
Exam batch uploads validate all files before saving any. Telegram downloads check
available size metadata and actual downloaded size; ingestion validates the
local file before storing it. These are format checks, not a malware scanner or
full parser validity guarantee. Direct Python model `.save()` does not invoke
Django validators; custom ingestion paths call validation explicitly.

The allowed document formats cover PDF, Office documents, plain text/CSV, and
common raster images. Unsupported formats require an explicit implementation
change. Disk spooling limits RAM, not total HTTP body size: configure a suitable
platform/proxy request-size limit if needed for the deployed upload workflow.

Phase 3's bounded OCR and single-child extraction remain in use: at most 100 PDF
pages, one rendered page at a time, bounded image dimensions/time, no all-page
fallback. Large digital PDFs within the page limit use digital extraction even
when too large for OCR. Exam schedule and attendance digital parsers now enforce
the same page limit. Attendance OCR correctly consumes the structured extraction
result and refuses partial OCR imports instead of treating the result object as
text.

## File safety and retention

Resource-delete admin views now remove database records without immediately
deleting the stored object. This protects shared inbox/resource/exam-upload
files. Existing duplicate cleanup also checks all three file-reference models
before deleting an unreferenced duplicate. It remains scheduled in maintenance,
with no ingestion-time bucket sweep.

Use a bounded **read-only** orphan audit:

```bash
python manage.py audit_orphan_files --prefix inbox --limit 500
python manage.py audit_orphan_files --prefix resources --limit 500
python manage.py audit_orphan_files --prefix exam_pdfs --limit 500
```

Only managed prefixes are inspected; default minimum object age is 30 days.
S3 listing returns a lexical `--after` cursor when more keys remain. The audit
checks references across resources, inbox items, and exam uploads and never
deletes files. Object age does not prove how long it has been orphaned. Review
candidates against current references and retained database/media backups, stop
producers during an approved deletion window, and recheck references before
manual deletion. An automated deletion job is intentionally not introduced.
Failed uploads, assigned files, and their records remain for explicit review.

Completed work can be compacted after 90 days, at most 500 records per type:

```bash
python manage.py compact_completed_work          # report only
python manage.py compact_completed_work --apply  # explicit reviewed compaction
```

This clears completed webhook payloads, delivered message text, and completed
AI source/chunk bodies. Update IDs, delivery deduplication keys, recipient/status
records, AI hashes/versions/results, and generated questions remain. Pending and
failed work retains its retry input. Daily maintenance reports compaction
candidates; it does not apply compaction automatically. Cached results are
retained to prevent repeat paid extraction. No production data was compacted.
Worker-owned temporary directories already clean up on normal exit/timeout;
forcibly killed parent leftovers remain container/platform cleanup work.

## Verification and measured impact

PostgreSQL 18.6 passes all 144 tests. SQLite runs 144: 137 pass and seven
database-specific checks skip. Coverage includes offline Signature V4 generation despite old unsigned
settings, no R2 file opening during URL issuance, free resource delivery, local
inline/expired URLs, legacy R2 redirects, validators, protected orphan references,
and compaction preserving failed work and update identities. Tests do not contact
R2. Migration drift, system checks, and synthetic database/media restore pass.

Verified architectural change: the R2 issuance path performs zero file reads;
previously each file transfer occupied a Django worker. Actual bandwidth, worker
memory, latency, storage operations, and bill changes remain unmeasured. Record
these in Railway against Phase 1 before claiming savings. In particular, signing
URLs does not establish browser/mobile usability or R2 header compatibility.

Deploy migrations content 0016 and exams 0006, restart web/worker services, and
verify representative large PDF/Office/image files, browser Range previews,
expiry/refresh, Unicode filenames, Telegram Android/iOS downloads, and local
fallback. Run hosted CI's OCR smoke check. Confirm Phase 3 services are running.
Phase 4 repository work is complete; live integration and cost checks remain open.
