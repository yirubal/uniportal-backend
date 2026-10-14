"""Shared production/container configuration; DEBUG is an explicit local opt-in."""

import os

from .base import *


DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

SECRET_KEY = env('SECRET_KEY', default='')
if not SECRET_KEY:
    raise ValueError('SECRET_KEY environment variable is not set.')

# Database
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': env.db('DATABASE_URL'),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': env('DB_ENGINE', default='django.db.backends.postgresql'),
            'NAME': env('DB_NAME', default='uniportal'),
            'USER': env('DB_USER', default='postgres'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='postgres'),
            'PORT': env('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
            'OPTIONS': {
                'connect_timeout': 10,
            },
        },
    }

# Security headers and proxy support. Dockploy should terminate TLS at the proxy.
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if env.bool('TRUST_PROXY_HTTPS', default=False) else None
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)  # Enable after TLS/proxy verification.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = 'DENY'

# CORS / CSRF
CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=env.list('ALLOWED_ORIGIN', default=['http://localhost:3000', 'http://localhost:5173']),
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# Static files are served locally by WhiteNoise. Media can use local storage or R2.
MIDDLEWARE = [
    'apps.api.middleware.RequestLogMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.api.middleware.TelegramAuthMiddleware',
]

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

USE_S3 = env.bool('USE_S3', default=not DEBUG)
if USE_S3:
    AWS_ACCESS_KEY_ID = env('R2_ACCESS_KEY_ID', default=env('AWS_ACCESS_KEY_ID', default=''))
    AWS_SECRET_ACCESS_KEY = env('R2_SECRET_ACCESS_KEY', default=env('AWS_SECRET_ACCESS_KEY', default=''))
    AWS_STORAGE_BUCKET_NAME = env(
        'R2_BUCKET_NAME',
        default=env('AWS_STORAGE_BUCKET_NAME', default='uniportal-media'),
    )
    R2_ACCOUNT_ID = env('R2_ACCOUNT_ID', default='')
    AWS_S3_ENDPOINT_URL = env('R2_ENDPOINT_URL', default=env('AWS_S3_ENDPOINT_URL', default=''))
    if not AWS_S3_ENDPOINT_URL and R2_ACCOUNT_ID:
        AWS_S3_ENDPOINT_URL = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'


    missing = [
        name
        for name, value in {
            'R2_ACCESS_KEY_ID or AWS_ACCESS_KEY_ID': AWS_ACCESS_KEY_ID,
            'R2_SECRET_ACCESS_KEY or AWS_SECRET_ACCESS_KEY': AWS_SECRET_ACCESS_KEY,
            'R2_BUCKET_NAME or AWS_STORAGE_BUCKET_NAME': AWS_STORAGE_BUCKET_NAME,
            'R2_ENDPOINT_URL/AWS_S3_ENDPOINT_URL or R2_ACCOUNT_ID': AWS_S3_ENDPOINT_URL,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f'Missing required R2 configuration: {", ".join(missing)}')

    AWS_S3_REGION_NAME = env('AWS_S3_REGION_NAME', default='auto')
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = True

    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
    }

# Telegram / AI aliases. Keep GOOGLE_API_KEY as a deployment alias for Gemini.
TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_ADMIN_CHAT_ID = env('TELEGRAM_ADMIN_CHAT_ID', default='')
TELEGRAM_CHANNEL_ID = env('TELEGRAM_CHANNEL_ID', default='')
TELEGRAM_OFFICIAL_CHANNEL_ID = env('TELEGRAM_OFFICIAL_CHANNEL_ID', default='')
TELEGRAM_WEBHOOK_SECRET = env('TELEGRAM_WEBHOOK_SECRET', default='')
TELEGRAM_WEBHOOK_URL = env('TELEGRAM_WEBHOOK_URL', default='')
TELEGRAM_CHANNEL_LINK = env('TELEGRAM_CHANNEL_LINK', default='https://t.me/unityuniversityportal')
MINI_APP_URL = env('MINI_APP_URL', default='')
GROQ_API_KEY = env('GROQ_API_KEY', default='')
GEMINI_API_KEY = env('GEMINI_API_KEY', default=env('GOOGLE_API_KEY', default=''))

REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
]

LOGGING['root']['handlers'] = ['console']
LOGGING['root']['level'] = env('LOG_LEVEL', default='INFO')
LOGGING['loggers']['django']['level'] = env('LOG_LEVEL', default='INFO')
LOGGING['loggers']['apps']['level'] = env('APP_LOG_LEVEL', default='INFO')

# Storage links (including admin file widgets) must use the signed S3 endpoint.
AWS_S3_CUSTOM_DOMAIN = None
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_QUERYSTRING_EXPIRE = RESOURCE_LINK_TTL_SECONDS
AWS_S3_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE

WHITENOISE_USE_FINDERS = False
WHITENOISE_AUTOREFRESH = False
STORAGES['staticfiles'] = {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}
DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
if DATABASES['default']['CONN_MAX_AGE'] < 0:
    raise ValueError('DB_CONN_MAX_AGE must be nonnegative.')
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default'].setdefault('OPTIONS', {})['connect_timeout'] = 10

if not DEBUG:
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('django-insecure-'):
        raise ValueError('Production SECRET_KEY must be random, at least 50 characters, and not a development key.')
    for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET', 'TELEGRAM_CHANNEL_ID'):
        value = globals()[name]
        if not value or value.startswith(('test-', 'your-')):
            raise ValueError(f'{name} is required in production.')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', TELEGRAM_WEBHOOK_SECRET):
        raise ValueError('TELEGRAM_WEBHOOK_SECRET must use Telegram allowed characters (1–256).')
    if not re.fullmatch(r'-[0-9]+', TELEGRAM_CHANNEL_ID):
        raise ValueError('TELEGRAM_CHANNEL_ID must be a numeric source channel ID.')
    if not env('ALLOWED_HOSTS', default='') or not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
        raise ValueError('Explicit ALLOWED_HOSTS are required in production.')
    if not os.environ.get('DATABASE_URL') or DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
        raise ValueError('Production requires a PostgreSQL DATABASE_URL.')

# Platform retention bounds console logs; no growing ephemeral log files.
# HTTP client INFO logs include Telegram bot-token URLs.
for name in ('httpx', 'httpcore', 'telegram'):
    LOGGING['loggers'][name] = {'handlers': ['console'], 'level': 'ERROR', 'propagate': False}
LOGGING['loggers']['django.request'] = {'handlers': ['console'], 'level': 'CRITICAL', 'propagate': False}
