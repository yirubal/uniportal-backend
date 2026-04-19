"""
apps/accounts/management/commands/check_subscriptions.py

Run this command to expire premium subscriptions that have passed their expiry date.
Set up as a daily cron job or Celery beat task.

Usage:
    python manage.py check_subscriptions
    python manage.py check_subscriptions --notify   # send Telegram warning 3 days before expiry
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Expires premium subscriptions that have passed their expiry date.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--notify',
            action='store_true',
            help='Send Telegram warning to students expiring within 3 days.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would happen without making any changes.',
        )

    def handle(self, *args, **options):
        from apps.accounts.models import Student

        now     = timezone.now()
        dry_run = options['dry_run']
        notify  = options['notify']

        # ── 1. Expire overdue subscriptions ───────────────────────────────────
        expired = Student.objects.filter(
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
            subscription_expiry__lt=now,
        )

        count = expired.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'[DRY RUN] Would expire {count} subscription(s).')
            )
            for s in expired:
                self.stdout.write(f'  - {s} expired on {s.subscription_expiry}')
        else:
            expired.update(subscription_status=Student.SUBSCRIPTION_FREE)
            self.stdout.write(
                self.style.SUCCESS(f'✅ Expired {count} subscription(s).')
            )

        # ── 2. Notify students expiring within 3 days ─────────────────────────
        if notify:
            from datetime import timedelta
            from django.conf import settings
            import requests as http_requests

            warning_threshold = now + timedelta(days=3)

            expiring_soon = Student.objects.filter(
                subscription_status=Student.SUBSCRIPTION_PREMIUM,
                subscription_expiry__gte=now,
                subscription_expiry__lte=warning_threshold,
            )

            notified = 0
            for student in expiring_soon:
                days_left = student.days_remaining
                expiry    = student.subscription_expiry.strftime('%B %d, %Y')
                name      = student.first_name or 'Student'

                text = (
                    f"⏰ *Subscription Expiring Soon*\n\n"
                    f"Hi {name}, your premium subscription expires in "
                    f"*{days_left} day{'s' if days_left != 1 else ''}* on {expiry}.\n\n"
                    f"Renew now to keep access to all study materials and exit exam questions. 📚"
                )

                try:
                    http_requests.post(
                        f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
                        json={
                            'chat_id':    student.telegram_id,
                            'text':       text,
                            'parse_mode': 'Markdown',
                        },
                        timeout=10,
                    )
                    notified += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'  Failed to notify {student}: {e}')
                    )

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f'[DRY RUN] Would notify {expiring_soon.count()} student(s) expiring within 3 days.'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'📨 Sent expiry warnings to {notified} student(s).')
                )