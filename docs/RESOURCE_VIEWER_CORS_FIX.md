# Resource viewer: failed to fetch

Production inspection on 2026-10-15 confirmed a storage CORS failure for the
configured frontend origin, `https://unityuni.vercel.app`.

The frontend's `DocumentViewerScreen` requests a fresh resource detail, then
fetches its signed `file_url` before rendering the bytes. Live signed requests
for published resources 397, 396 and 395 returned HTTP 200, PDF content types and
valid PDF signatures when sent with that frontend Origin header. All three lacked
`Access-Control-Allow-Origin`. Browsers block reading such cross-origin responses,
which produces the viewer's “Failed to fetch” error.

No frontend code change or backend download proxy is required for this confirmed
failure. The private R2 bucket must allow the deployed frontend origin to read
signed files. API CORS settings on Django do not configure responses from R2.

## Apply the storage policy

In Cloudflare, open the app's R2 bucket → Settings → CORS policy. Add the rule in
[R2_CORS_POLICY.json](R2_CORS_POLICY.json). If a policy already exists, preserve
its unrelated rules/origins and merge this rule rather than replacing them.

The rule allows GET/HEAD reads from the production frontend and optional Range
requests. It exposes file metadata headers. Keep public access disabled; signed
URL authentication remains required. No bucket-public-access change is needed.

The current Railway runtime R2 credentials permit object reads, but a live
`GetBucketCors` request returned `AccessDenied`. No Cloudflare administrative token
or authenticated Wrangler profile was available. The policy is prepared, but its
application is NOT verified. Use the dashboard or separate bucket-administration
credentials; the application does not need broader credentials for normal reads.

## Verify after application

Request a NEW signed file URL with:

```text
Origin: https://unityuni.vercel.app
```

The GET response must return HTTP 200 and:

```text
Access-Control-Allow-Origin: https://unityuni.vercel.app
```

An OPTIONS check for GET with `Access-Control-Request-Headers: range` should also
succeed. Reload the resource in the live frontend and verify that a PDF opens.
Do not publish signed URLs or access keys in logs. Cloudflare notes that policy
propagation can occasionally take up to 30 seconds.

Reference: [Cloudflare R2 CORS documentation](https://developers.cloudflare.com/r2/buckets/cors/).
