# Production backup and maintenance

Implementation: 2026-10-15. Live backup/restore and maintenance deployment results
will be recorded below after verification.

## Arrangement

The owner selected the existing private R2 bucket for backups. The production
PostgreSQL volume had no snapshots/schedule, and PITR was disabled. The attempt to
enable Railway's daily volume snapshots was rejected with “Manual backups and
backup schedules are only available for Pro workspaces.” No plan was upgraded.

`python manage.py backup_production` makes a PostgreSQL custom-format dump and
copies media into `operations/backups/daily-v1/` in the existing private bucket.
The database dump and table row hashes share one exported read-only PostgreSQL
snapshot. The backup refuses completion if a referenced media key is missing.
The source database stays online; no source records are changed.

Media backup keys depend on the source key and ETag. New versions are hashed,
copied server-side with an ETag condition, then read back and hash-verified.
Unchanged copies are reused after size/hash-metadata checks. Four I/O threads
bound transfer concurrency; files are streamed rather than loaded into memory.
All non-backup bucket objects are included, including files currently unreferenced
by Django. Backups do not recursively back up other backup objects.

Each completed snapshot has a private JSON manifest with original file keys,
backup locations, sizes, SHA-256 hashes, table counts/hashes and completion times.
The manifest is uploaded and verified last, after database and media validation.
Database dumps are read back and hash-verified. A failure before this marker is
written leaves an incomplete run, which cannot authorize maintenance.

Completed snapshots are retained for 30 days. Expired database snapshots and
media versions unused by any retained snapshot are removed only within the
`daily-v1` namespace. Recent partial copies remain available for retries; old
standalone partial database objects may need operator cleanup. Earlier exam-row
cleanup backups and application files are outside this retention operation.

The backup is in the same bucket/account as live media and uses the application's
existing credentials. It protects against ordinary application deletion or
replacement but does not protect against bucket/account loss or an attacker with
those credentials. It is not an independent off-account backup. A separate private
destination remains a future improvement; public bucket access stays disabled.

## Scheduled service

The daily role runs:

```bash
python manage.py run_maintenance --backup
```

Schedule: `0 3 * * *` (03:00 UTC / 06:00 Nairobi), one replica, restart policy
`NEVER`, no public domain, no HTTP health check and no pre-deploy migrations.
Only web owns migrations. Railway's new services reject legacy JSON config-file
paths, so configure equivalent service settings explicitly. The committed
`railway-maintenance.json` records the intended role configuration.

Backup failure stops the command before subscription expiry, reminder production,
inbox cleanup, work-compaction reporting or expired throttle-row cleanup. A failed
backup therefore also delays maintenance until an operator fixes/retries it.
Maintenance does not send subscription marketing/expiry warnings. Existing free
adoption/access rules remain unchanged. The worker delivers due exam reminders.

The container now installs PostgreSQL client 18 from the PostgreSQL project's
signed Debian repository. Its previous default client 17 could not dump the
production PostgreSQL 18 server. Credentials are supplied to pg_dump through
environment variables, never command arguments or backup manifests. Failures log
only an error type; do not print subprocess stderr or private manifests.

Cost: one small daily database dump plus media copies for new/changed objects,
R2 requests and retained storage. Unchanged media are not recopied every day.
Initial bucket inventory was 564 media objects / 758,163,668 bytes, with a roughly
30 MB PostgreSQL database. These counts do not establish a monthly bill. Daily
unchanged-copy checks inspect metadata; periodically repeat full restore/hash
verification to check the actual stored bytes.

## Recovery procedure

1. Select a completed private snapshot manifest and download its database dump.
   Verify its SHA-256 before using it. Never publish the manifest or signed URLs.
2. Restore into a fresh isolated PostgreSQL instance with a compatible client:
   `pg_restore --exit-on-error --no-owner --no-privileges --dbname=<isolated_db> database.dump`.
   Never target the live database for a rehearsal.
3. Restore each manifest media entry under its original key in isolated storage;
   validate its size and SHA-256. Treat keys as untrusted local paths if restoring
   to disk: reject absolute paths and traversal, or use hashed temporary filenames.
4. Compare all public table row counts/hashes with the manifest. Normalize the
   fingerprint session timezone to UTC. Verify Django model reads, relationships,
   file references and relevant student flows without production Telegram/AI keys.
5. For an actual production recovery, stop workers, maintenance and writes before
   switching to a matched database/media set. Roles, infrastructure, credentials
   and provider configuration need separate recovery; pg_dump does not back them up.

PostgreSQL and R2 cannot provide a single atomic cross-system snapshot. Media are
checked against the captured database references and copied conditionally;
concurrent file changes or missing files can fail a run for retry. This does not
capture arbitrary external Telegram/AI side effects. A completed backup is recovery
evidence, not proof that the original academic content is correct.

## Verification

Twelve tests cover real pg_dump completion/missing-media refusal on PostgreSQL,
media-version reuse, changed-source detection, corrupt-copy/metadata refusal,
retention boundaries, correct private credential handling and maintenance ordering.
Full PostgreSQL suite: 271 tests pass. The rebuilt container passes 271 tests with
11 PostgreSQL-only skips, dependency checks and real image/scanned-PDF OCR checks.
Live restore results pending.
No new database migration or Python dependency is required.

References: [Railway backups](https://docs.railway.com/volumes/backups),
[PostgreSQL Debian packages](https://www.postgresql.org/download/linux/debian/),
[R2 S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/).
