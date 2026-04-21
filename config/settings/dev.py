from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

# Show browsable API in development
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',
]

# Relaxed throttling in dev
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon':         '1000/minute',
    'user':         '1000/minute',
    'auth':         '1000/minute',
    'subscription': '1000/minute',
}

# CORS — allow all in dev
CORS_ALLOW_ALL_ORIGINS = True

# No HTTPS enforcement in dev
SECURE_SSL_REDIRECT = False