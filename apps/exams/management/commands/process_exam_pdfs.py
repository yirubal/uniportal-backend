from django.core.management.base import BaseCommand
from django.db import connections


class Command(BaseCommand):
    help = 'Processes pending exam PDF uploads.'

    def handle(self, *args, **options):
        from apps.exams.models import ExamPDFUpload
        from apps.exams.services import process_attendance_pdf, process_schedule_pdf

        pending_upload_ids = list(ExamPDFUpload.objects.filter(
            status=ExamPDFUpload.STATUS_PENDING,
        ).order_by('uploaded_at').values_list('pk', flat=True))

        total = len(pending_upload_ids)
        if total == 0:
            self.stdout.write('No pending exam PDF uploads.')
            connections.close_all()
            return

        self.stdout.write(f'Processing {total} pending exam PDF upload(s)...')

        processed = 0
        failed = 0
        skipped = 0

        for upload_id in pending_upload_ids:
            claimed = ExamPDFUpload.objects.filter(
                pk=upload_id,
                status=ExamPDFUpload.STATUS_PENDING,
            ).update(
                status=ExamPDFUpload.STATUS_PROCESSING,
                error_message='',
            )
            if not claimed:
                skipped += 1
                continue

            upload = ExamPDFUpload.objects.get(pk=upload_id)
            self.stdout.write(f'Processing #{upload.pk}: {upload.original_name}')

            try:
                if upload.pdf_type == ExamPDFUpload.TYPE_SCHEDULE:
                    success, created, error = process_schedule_pdf(upload)
                elif upload.pdf_type == ExamPDFUpload.TYPE_ATTENDANCE:
                    success, created, error = process_attendance_pdf(upload)
                else:
                    raise ValueError(f'Unsupported PDF type: {upload.pdf_type}')
            except Exception as exc:
                success = False
                created = 0
                error = str(exc)

            upload.refresh_from_db()
            if upload.status == ExamPDFUpload.STATUS_PROCESSING:
                upload.status = (
                    ExamPDFUpload.STATUS_PROCESSED if success else ExamPDFUpload.STATUS_FAILED
                )
                upload.records_created = created if success else 0
                upload.error_message = '' if success else error
                upload.save(update_fields=['status', 'records_created', 'error_message'])

            if success:
                processed += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Processed #{upload.pk}: {created} record(s) created')
                )
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f'Failed #{upload.pk}: {error}'))

        connections.close_all()
        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Processed={processed}, failed={failed}, skipped={skipped}.'
            )
        )
