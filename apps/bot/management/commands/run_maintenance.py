from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.api.models import ThrottleCacheEntry


class Command(BaseCommand):
    help = 'Daily maintenance: expire subscriptions, queue exam reminders, clean up 100 assigned inbox references.'

    def handle(self, *args, **options):
        call_command('check_subscriptions', stdout=self.stdout)
        call_command('send_exam_notifications', stdout=self.stdout)
        call_command('cleanup_duplicate_inbox_files', limit=100, stdout=self.stdout)
        call_command('compact_completed_work', stdout=self.stdout)  # Report only; applying compaction is explicit.
        expired, _ = ThrottleCacheEntry.objects.filter(expires__lt=timezone.now()).delete()
        self.stdout.write(f'Removed {expired} expired throttle history row(s).')
