"""Collect static assets without production credentials or database access."""
import os
import sys

if 'collectstatic' not in sys.argv:
    raise ValueError('Build settings are only for collectstatic, never serving requests.')

os.environ['SECRET_KEY'] = 'static-build-only-never-use-this-settings-module-to-serve-requests'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from .base import *

DEBUG = False
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
