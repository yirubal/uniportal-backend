"""Persist due exam reminders; the worker delivers and retries each recipient."""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Queue exam reminders due 15, 7, and 3 days before the active term.'

    def handle(self, *args, **options):
        from apps.accounts.models import Student
        from apps.accounts.notifications import send_telegram_message
        from apps.exams.models import ExamNotificationLog, ExamTerm
        term = ExamTerm.objects.filter(is_active=True).first()
        if not term or not term.exam_start_date:
            self.stdout.write('No active exam start date; no reminders due.')
            return
        days = (term.exam_start_date - timezone.localdate()).days
        if days not in {15, 7, 3}:
            self.stdout.write('No exam reminders due today.')
            return
        text = f'📅 {term} exams begin in {days} days, on {term.exam_start_date:%B %d, %Y}.\n\nOpen UniPortal → Exam Schedule to find your room and time.'
        with transaction.atomic():
            # One producer owns the log and all associated delivery intents.
            ExamTerm.objects.select_for_update().get(pk=term.pk)
            if ExamNotificationLog.objects.filter(term=term, days_before=days).exists():
                self.stdout.write('Exam reminders already queued.')
                return
            log = ExamNotificationLog.objects.create(term=term, days_before=days)
            for chat_id in Student.objects.filter(is_active=True).values_list('telegram_id', flat=True).iterator(chunk_size=500):
                send_telegram_message(chat_id, text, deduplication_key=f'exam:{term.pk}:{days}:{chat_id}', exam_notification=log)
        self.stdout.write(f'Queued {days}-day reminders. Delivery status is in Bot > Notification deliveries.')
