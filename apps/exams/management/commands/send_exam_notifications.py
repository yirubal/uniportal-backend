"""
Sends exam approach notifications to students via Telegram.
"""

import asyncio

from django.core.management.base import BaseCommand
from django.utils import timezone

NOTIFICATION_DAYS = [15, 7, 3]


class Command(BaseCommand):
    help = 'Sends exam countdown notifications to all registered students'

    def handle(self, *args, **kwargs):
        from django.conf import settings
        from telegram import Bot

        from apps.accounts.models import Student
        from apps.exams.models import ExamNotificationLog, ExamTerm

        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            self.stdout.write('No active exam term — skipping notifications')
            return

        if not term.exam_start_date:
            self.stdout.write('No exam start date set on active term — skipping')
            return

        today = timezone.now().date()
        days_until = (term.exam_start_date - today).days

        self.stdout.write(f'Exam starts in {days_until} days ({term.exam_start_date})')

        if days_until not in NOTIFICATION_DAYS:
            self.stdout.write(f'No notification due today (days={days_until})')
            return

        already_sent = ExamNotificationLog.objects.filter(
            term=term,
            days_before=days_until,
        ).exists()
        if already_sent:
            self.stdout.write(f'{days_until}-day notification already sent — skipping')
            return

        students = list(Student.objects.filter(is_active=True).only('telegram_id'))
        self.stdout.write(f'Sending {days_until}-day notification to {len(students)} students...')

        sent = 0
        failed = 0

        async def send_notifications():
            nonlocal sent, failed
            bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

            if days_until == 15:
                emoji = '📅'
                urgency = 'Exam season is approaching!'
                tip = 'Start reviewing your notes and materials now.'
            elif days_until == 7:
                emoji = '⏰'
                urgency = 'One week until exams!'
                tip = 'Make sure you know your exam room and schedule.'
            else:
                emoji = '🚨'
                urgency = 'Exams start in 3 days!'
                tip = 'Check your exam room on UniPortal now.'

            message = (
                f'{emoji} *{urgency}*\n\n'
                f'*{term}* exams begin on '
                f'*{term.exam_start_date.strftime("%A, %B %d, %Y")}*\n\n'
                f'💡 {tip}\n\n'
                f'📋 Open UniPortal → Exam Schedule to find your room and time.'
            )

            for student in students:
                try:
                    await bot.send_message(
                        chat_id=student.telegram_id,
                        text=message,
                        parse_mode='Markdown',
                    )
                    sent += 1
                except Exception:
                    failed += 1

        asyncio.run(send_notifications())

        ExamNotificationLog.objects.create(
            term=term,
            days_before=days_until,
            sent_count=sent,
            failed_count=failed,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Sent {days_until}-day notification: {sent} delivered, {failed} failed'
            )
        )
