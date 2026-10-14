import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from apps.bot.worker import claim_work, recover_stale_claims, run_claimed_subprocess, work_types


class Command(BaseCommand):
    help = 'Run one durable worker for Telegram, notifications, documents, and AI.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='One bounded pass through each work type.')
        parser.add_argument('--poll-interval', type=float, default=2)

    def handle(self, *args, **options):
        if options['poll_interval'] <= 0:
            raise CommandError('Poll interval must be positive.')
        if settings.WORKER_TASK_TIMEOUT_SECONDS >= settings.WORKER_CLAIM_TIMEOUT_SECONDS:
            raise CommandError('Claim expiry must exceed the subprocess deadline.')
        stopped = False
        last_recovery = 0

        def stop(signum, frame):
            nonlocal stopped
            stopped = True
            # Interrupt a wait so the child and its OCR descendants are killed.
            raise KeyboardInterrupt

        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            self.stdout.write('Durable worker started; concurrency=1.')
            while not stopped:
                close_old_connections()
                if time.monotonic() - last_recovery >= 60:
                    recover_stale_claims()
                    last_recovery = time.monotonic()
                worked = False
                # A round-robin pass prevents broadcasts starving document jobs.
                for kind in work_types():
                    claim = claim_work(kind)
                    if claim:
                        worked = True
                        self.stdout.write(f'Processing {kind} #{claim[0]}')
                        run_claimed_subprocess(kind, *claim)
                if options['once']:
                    break
                time.sleep(0.1 if worked else options['poll_interval'])
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped; interrupted claims recover after expiry.')
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
