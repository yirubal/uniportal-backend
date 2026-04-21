from .base import *

DEBUG = False

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# ── Security headers ──────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT             = True
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
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

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