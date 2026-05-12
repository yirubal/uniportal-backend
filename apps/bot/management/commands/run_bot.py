"""
In webhook mode this command is no longer needed for bot polling.

Bot updates are handled by the web service via:
  POST /api/telegram/webhook/
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Verifies bot webhook mode and runs inbox recovery tasks'

    def handle(self, *args, **kwargs):
        from apps.bot.tasks import recover_failed_inbox_items, recover_stuck_inbox_items

        self.stdout.write('UniPortal Bot - Webhook Mode')
        self.stdout.write('Bot updates are handled by the web service.')
        self.stdout.write('Run: python manage.py setup_webhook to register the webhook.')

        recover_stuck_inbox_items()
        recover_failed_inbox_items()

        self.stdout.write(self.style.SUCCESS('Inbox recovery complete.'))
