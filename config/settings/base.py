import environ
import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(DEBUG=(bool, False))
if env.bool('READ_DOT_ENV', default=True):
    environ.Env.read_env(BASE_DIR / '.env')

# ── Core ──────────────────────────────────────────────────────────────────────
SECRET_KEY = env('SECRET_KEY')
DEBUG      = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# ── Apps ──────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',

    # Third party
    'rest_framework',
    'corsheaders',
    'drf_spectacular',

    # Local
    'apps.accounts.apps.AccountsConfig',
    'apps.content',
    'apps.quiz',
    'apps.exams.apps.ExamsConfig',
    'apps.bot',
    'apps.api',
]

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'apps.api.middleware.RequestLogMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.api.middleware.TelegramAuthMiddleware',
]

ROOT_URLCONF    = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR}/db.sqlite3')
}

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── i18n ──────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Addis_Ababa'
USE_I18N      = True
USE_TZ        = True

# ── Static & Media ────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL   = '/media/'
MEDIA_ROOT  = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_EXPOSE_HEADERS = ['X-Quiz-Simulation-ID', 'X-Request-ID']

# ── REST Framework ────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'apps.api.throttles.StudentAwareAnonThrottle',
        'apps.api.throttles.StudentRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '100/minute',
        'auth': '10/minute',       # login attempts
        'subscription': '5/minute', # payment requests
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# ── JWT ───────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'AUTH_HEADER_TYPES':      ('Bearer',),
}

# ── API Docs (drf-spectacular) ────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE':       'UniPortal API',
    'DESCRIPTION': (
        'REST API for Unity University Student Portal. '
        'Provides access to study materials, quiz questions, '
        'exit exam practice, and subscription management.'
    ),
    'VERSION':            '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'persistAuthorization': True,
        'displayRequestDuration': True,
        'filter': True,
    },
    'COMPONENT_SPLIT_REQUEST': True,
    'TAGS': [
        {'name': 'Auth',          'description': 'Telegram authentication'},
        {'name': 'Students',      'description': 'Student profile and preferences'},
        {'name': 'Departments',   'description': 'Department listing'},
        {'name': 'Courses',       'description': 'Course listing by department'},
        {'name': 'Resources',     'description': 'Study materials and downloads'},
        {'name': 'Exams',         'description': 'Exam papers and questions'},
        {'name': 'Quiz',          'description': 'Quiz attempts and performance'},
        {'name': 'Subscription',  'description': 'Plans and payment requests'},
    ],
}

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN          = env('TELEGRAM_BOT_TOKEN',          default='')
TELEGRAM_ADMIN_CHAT_ID      = env('TELEGRAM_ADMIN_CHAT_ID',      default='')
TELEGRAM_CHANNEL_ID         = env('TELEGRAM_CHANNEL_ID',         default='')   # resource-upload channel
TELEGRAM_OFFICIAL_CHANNEL_ID = env('TELEGRAM_OFFICIAL_CHANNEL_ID', default='') # public channel users must join
TELEGRAM_WEBHOOK_SECRET     = env('TELEGRAM_WEBHOOK_SECRET',     default='')
TELEGRAM_WEBHOOK_URL        = env(
    'TELEGRAM_WEBHOOK_URL',
    default='https://web-production-312b.up.railway.app/api/telegram/webhook/',
)
# Public link shown to users who haven't joined yet
TELEGRAM_CHANNEL_LINK = env('TELEGRAM_CHANNEL_LINK', default='https://t.me/unityuniversityportal')
MINI_APP_URL = env('MINI_APP_URL', default='')
GROQ_API_KEY         = env('GROQ_API_KEY',         default='')
GEMINI_API_KEY       = env('GEMINI_API_KEY',       default='')

# ── File uploads ──────────────────────────────────────────────────────────────
# config/settings/base.py
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024  # Spool larger files to disk.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# ── Unfold Admin ──────────────────────────────────────────────────────────────
UNFOLD = {
    'SITE_TITLE':    'UniPortal Admin',
    'DASHBOARD_CALLBACK': 'config.admin_dashboard.dashboard',
    'SITE_HEADER':   'Unity University',
    'SITE_SUBHEADER': 'Student Portal',
    'SITE_URL':      '/',
    'SITE_SYMBOL':   'school',
    'SHOW_HISTORY':  True,
    'SHOW_VIEW_ON_SITE': False,
    'COLORS': {
        'primary': {
            '50':  '240 249 255',
            '100': '224 242 254',
            '200': '186 230 253',
            '300': '125 211 252',
            '400': '56 189 248',
            '500': '14 165 233',
            '600': '2 132 199',
            '700': '3 105 161',
            '800': '7 89 133',
            '900': '12 74 110',
            '950': '8 47 73',
        },
    },
    'SIDEBAR': {
        'show_search':       True,
        'show_all_applications': False,
        'navigation': 'config.admin_dashboard.navigation',
    },
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style':  '{',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level':    'INFO',
    },
    'loggers': {
        'django': {
            'handlers':  ['console'],
            'level':     'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers':  ['console'],
            'level':     'DEBUG',
            'propagate': False,
        },
    },
}

# A single worker bounds memory; subprocess deadlines stay below claim expiry.
WORKER_TASK_TIMEOUT_SECONDS = 300
WORKER_CLAIM_TIMEOUT_SECONDS = 900
WORKER_MAX_ATTEMPTS = 5
EXTRACTION_MAX_PAGES = 100
EXTRACTION_TIMEOUT_SECONDS = 240
OCR_MAX_FILE_BYTES = 5 * 1024 * 1024
AI_MAX_INPUT_CHARS = 40000
AI_MAX_QUESTIONS = 500
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')

RESOURCE_LINK_TTL_SECONDS = 900
MAX_DOCUMENT_UPLOAD_BYTES = env.int('MAX_DOCUMENT_UPLOAD_BYTES', default=100 * 1024 * 1024)
MAX_EXAM_PDF_UPLOAD_BYTES = env.int('MAX_EXAM_PDF_UPLOAD_BYTES', default=20 * 1024 * 1024)

DATA_UPLOAD_MAX_NUMBER_FILES = 20

API_LEGACY_LIST_LIMIT = 500
MAX_EXAM_IMPORT_ROWS = 20000

# Only low-frequency auth/payment throttles need shared cross-worker histories.
# General traffic uses cheap process-local, approximate availability limits.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'uniportal-local'},
    'throttles': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
                  'LOCATION': 'api_throttle_cache', 'KEY_PREFIX': 'uniportal-throttle',
                  'OPTIONS': {'MAX_ENTRIES': 10000}},
}
REST_FRAMEWORK['NUM_PROXIES'] = env.int('THROTTLE_NUM_PROXIES', default=0)

if REST_FRAMEWORK['NUM_PROXIES'] < 0:
    raise ValueError('THROTTLE_NUM_PROXIES must be zero or a positive trusted-proxy count.')
