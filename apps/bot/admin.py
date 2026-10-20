from django.contrib import admin, messages
from django.utils import timezone
from apps.bot.admin_filters import WorkAttentionFilter
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import AutocompleteSelectFilter

from .models import NotificationDelivery, QuestionExtraction, TelegramUpdate


@admin.action(permissions=['change'], description='Retry selected failed records after review')
def retry_failed(model_admin, request, queryset):
    parents = list(queryset.filter(status='failed').values_list('broadcast_id', 'exam_notification_id')) if queryset.model is NotificationDelivery else []
    selected = queryset.count()
    count = queryset.filter(status='failed').update(
        status='pending', attempt_count=0, next_attempt_at=timezone.now(),
        claim_token=None, claimed_at=None, error_message='',
    )
    from .worker import refresh_broadcast, refresh_exam_reminder
    for broadcast_id, reminder_id in parents:
        refresh_broadcast(broadcast_id)
        refresh_exam_reminder(reminder_id)
    model_admin.message_user(request, f'Queued {count} failed record(s) for retry; {selected - count} non-failed record(s) skipped.', messages.SUCCESS)


retry_failed.short_description = 'Retry selected failed records after review'


@admin.register(TelegramUpdate)
class TelegramUpdateAdmin(ModelAdmin):
    list_display = ['update_id', 'status', 'attempt_count', 'next_attempt_at', 'claimed_at', 'created_at']
    list_filter = [WorkAttentionFilter, 'status']
    readonly_fields = [field.name for field in TelegramUpdate._meta.fields]
    actions = [retry_failed]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(ModelAdmin):
    list_select_related = ['broadcast', 'exam_notification']
    list_display = ['deduplication_key', 'broadcast', 'status', 'attempt_count', 'next_attempt_at', 'created_at']
    list_filter = [WorkAttentionFilter, 'status', ('broadcast', AutocompleteSelectFilter)]
    readonly_fields = [field.name for field in NotificationDelivery._meta.fields]
    actions = [retry_failed]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuestionExtraction)
class QuestionExtractionAdmin(ModelAdmin):
    list_select_related = ['exam_paper']
    list_display = ['id', 'source_label', 'exam_paper', 'status', 'provider_calls', 'attempt_count', 'next_attempt_at', 'created_at']
    list_filter = [WorkAttentionFilter, 'status']
    readonly_fields = [field.name for field in QuestionExtraction._meta.fields]
    actions = [retry_failed]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
