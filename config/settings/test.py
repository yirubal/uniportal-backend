"""Isolated local/CI checks; external services are disabled by default."""

import os
from tempfile import TemporaryDirectory

# Defaults are set before base.py reads .env. DATABASE_URL may explicitly select
# a disposable PostgreSQL database; otherwise checks use in-memory SQLite.
os.environ.setdefault('SECRET_KEY', 'uniportal-tests-only-not-for-production')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from .dev import *  # noqa: E402,F403

TELEGRAM_BOT_TOKEN = ''
TELEGRAM_ADMIN_CHAT_ID = ''
TELEGRAM_OFFICIAL_CHANNEL_ID = ''
TELEGRAM_WEBHOOK_SECRET = ''
GEMINI_API_KEY = ''
GROQ_API_KEY = ''

_test_media = TemporaryDirectory(prefix='uniportal-tests-media-')
MEDIA_ROOT = _test_media.name
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
