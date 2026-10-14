from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.bot.models import NotificationDelivery, QuestionExtraction, TelegramUpdate


class Command(BaseCommand):
    help = 'Compact old completed work; preserve deduplication identities, AI results, and all failed/pending records. Dry run by default.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, *args, **options):
        if options['days'] < 30 or not 1 <= options['limit'] <= 1000:
            raise CommandError('Retention must be at least 30 days; limit 1–1000.')
        cutoff = timezone.now() - timedelta(days=options['days'])
        queues = [
            (TelegramUpdate, {'payload': {}}),
            (NotificationDelivery, {'text': ''}),
            (QuestionExtraction, {'source_text': '', 'chunks': {}}),
        ]
        for model, changes in queues:
            queryset = model.objects.filter(status='processed', created_at__lt=cutoff)
            queryset = queryset.exclude(**changes)
            ids = list(queryset.order_by('pk').values_list('pk', flat=True)[:options['limit']])
            if options['apply']:
                model.objects.filter(pk__in=ids, status='processed').update(**changes)
            self.stdout.write(f'{model.__name__}: {len(ids)} record(s) {"compacted" if options["apply"] else "would be compacted"}.')
