"""The web role serves requests; schema changes belong to the release role."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
worker_class = 'sync'
threads = 1
worker_tmp_dir = '/dev/shm'
errorlog = '-'
# Request middleware logs route names, IDs, status and duration without URL tokens.
accesslog = None
