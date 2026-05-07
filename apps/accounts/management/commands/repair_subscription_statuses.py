from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Repairs student premium state so only students with approved active requests remain premium.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show rows that would be repaired without changing them.',
        )

    def handle(self, *args, **options):
        from apps.accounts.models import Student, SubscriptionRequest

        now = timezone.now()
        dry_run = options['dry_run']
        premium_students = Student.objects.filter(
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
        )
        repaired = 0

        for student in premium_students:
            has_valid_approval = SubscriptionRequest.objects.filter(
                student=student,
                status=SubscriptionRequest.STATUS_APPROVED,
                activated_at__isnull=False,
            ).exists()
            has_future_expiry = (
                student.subscription_expiry is not None
                and student.subscription_expiry > now
            )

            if has_valid_approval and has_future_expiry:
                continue

            repaired += 1
            self.stdout.write(
                f'{student} marked premium but has_valid_approval={has_valid_approval} '
                f'has_future_expiry={has_future_expiry}; setting to free.'
            )
            if not dry_run:
                student.subscription_status = Student.SUBSCRIPTION_FREE
                student.subscription_expiry = None
                student.save(update_fields=['subscription_status', 'subscription_expiry'])

        prefix = '[DRY RUN] Would repair' if dry_run else 'Repaired'
        self.stdout.write(self.style.SUCCESS(f'{prefix} {repaired} student subscription state(s).'))
