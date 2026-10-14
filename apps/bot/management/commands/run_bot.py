from django.core.management.base import BaseCommand
from apps.bot.worker import recover_stale_claims


class Command(BaseCommand):
    help = 'One-off recovery of stale claims; use run_worker for continuous processing.'

    def handle(self, *args, **options):
        count = recover_stale_claims()
        self.stdout.write(f'Recovered {count} stale claim(s). Failed records require explicit review/retry.')
