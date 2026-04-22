from .base import *

DEBUG = False

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# ── Security headers ──────────────────────────────────────────────────────────
# Disabled because Railway's internal healthchecks use plain HTTP. With this
# set to True, Django redirects every HTTP request to HTTPS, the healthcheck
# times out, and Railway kills the container. Once a custom healthcheck path
# (e.g. /health/) is in place and Railway is configured to use it, this can
# be re-enabled — or handled via SECURE_REDIRECT_EXEMPT for that path.
SECURE_SSL_REDIRECT             = False
SECURE_HSTS_SECONDS             = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS  = True
SECURE_HSTS_PRELOAD             = True
SECURE_CONTENT_TYPE_NOSNIFF     = True
SECURE_BROWSER_XSS_FILTER       = True
SESSION_COOKIE_SECURE           = True
CSRF_COOKIE_SECURE              = True
X_FRAME_OPTIONS                 = 'DENY'

# ── CORS — only allow frontend domain ─────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_CREDENTIALS = True

# ── Static files — whitenoise for production ──────────────────────────────────
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')


# ── No browsable API in production ────────────────────────────────────────────
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
]

# ── Logging to file in production ─────────────────────────────────────────────
LOGGING['handlers']['file'] = {
    'class':     'logging.FileHandler',
    'filename':  BASE_DIR / 'logs' / 'django.log',
    'formatter': 'verbose',
}
LOGGING['root']['handlers'] = ['console', 'file']


# ── Cloudflare R2 Storage ─────────────────────────────────────────────────────

AWS_ACCESS_KEY_ID       = env('R2_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY   = env('R2_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = env('R2_BUCKET_NAME', default='uniportal-media')
AWS_S3_ENDPOINT_URL     = f'https://{env("R2_ACCOUNT_ID")}.r2.cloudflarestorage.com'
AWS_S3_REGION_NAME      = 'auto'
AWS_DEFAULT_ACL         = 'public-read'
AWS_S3_FILE_OVERWRITE   = False
AWS_QUERYSTRING_AUTH    = False  # public URLs without signatures

STORAGES = {
    'default': {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# Media URL points to R2
MEDIA_URL = f'https://{env("R2_BUCKET_NAME", default="uniportal-media")}.{env("R2_ACCOUNT_ID")}.r2.cloudflarestorage.com/'