"""
Docker settings for UniPortal.

This module keeps the live project settings from base.py and only overrides the
pieces needed for containerized local testing and Dockploy deployment.
"""

import os

from .base import *


def _clean_url(value):
    return value.rstrip('/') if value else value


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
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'connect_timeout': 10,
            },
        },
    }

# Security headers and proxy support. Dockploy should terminate TLS at the proxy.
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)
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

USE_S3 = env.bool('USE_S3', default=False)
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

    R2_PUBLIC_URL = _clean_url(env('R2_PUBLIC_URL', default=env('AWS_S3_CUSTOM_DOMAIN', default='')))
    if R2_PUBLIC_URL:
        AWS_S3_CUSTOM_DOMAIN = (
            R2_PUBLIC_URL.replace('https://', '', 1).replace('http://', '', 1)
        )
        MEDIA_URL = f'{R2_PUBLIC_URL}/'
    elif R2_ACCOUNT_ID:
        MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/'

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
    AWS_DEFAULT_ACL = 'public-read'
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False

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
