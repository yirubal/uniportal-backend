from datetime import timedelta

from django.conf import settings
from django.contrib.admin import SimpleListFilter
from django.db.models import Q
from django.utils import timezone


def work_attention_conditions(status_field, now):
    """Shared definitions keep Overview counts and their destination lists equal."""
    return {
        'failed': Q(**{status_field: 'failed'}),
        'overdue': Q(**{f'{status_field}__in': ['pending', 'unprocessed'],
                        'next_attempt_at__lt': now - timedelta(minutes=15)}),
        'stale': Q(**{status_field: 'processing'}) & (
            Q(claimed_at__isnull=True)
            | Q(claimed_at__lt=now - timedelta(seconds=settings.WORKER_CLAIM_TIMEOUT_SECONDS))
        ),
    }


class WorkAttentionFilter(SimpleListFilter):
    title = 'needs attention'
    parameter_name = 'attention'

    def lookups(self, request, model_admin):
        return [('failed', 'Failed'), ('overdue', 'Pending over 15 minutes'),
                ('stale', 'Stale processing claim')]

    def queryset(self, request, queryset):
        status_field = 'processing_status' if queryset.model._meta.model_name == 'fileinbox' else 'status'
        condition = work_attention_conditions(status_field, timezone.now()).get(self.value())
        return queryset.filter(condition) if condition is not None else queryset
