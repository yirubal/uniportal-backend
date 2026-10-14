from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'One-off processing of eligible exam uploads with worker claiming/retries.'

    def handle(self, *args, **options):
        from apps.bot.worker import claim_work, run_claimed_subprocess, recover_stale_claims
        recover_stale_claims('exam')
        count = 0
        while claim := claim_work('exam'):
            run_claimed_subprocess('exam', *claim)
            count += 1
        self.stdout.write(f'Processed {count} eligible exam PDF upload(s).')
