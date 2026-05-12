web: python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
worker: python manage.py run_bot
exam_pdf_cron: python manage.py process_exam_pdfs
