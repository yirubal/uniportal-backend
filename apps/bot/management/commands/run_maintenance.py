from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Daily maintenance: expire subscriptions, queue exam reminders, clean up 100 assigned inbox references.'

    def handle(self, *args, **options):
        call_command('check_subscriptions', stdout=self.stdout)
        call_command('send_exam_notifications', stdout=self.stdout)
        call_command('cleanup_duplicate_inbox_files', limit=100, stdout=self.stdout)
