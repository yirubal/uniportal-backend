from django.db import models
from django.utils import timezone

WORK_STATUSES = [('pending', 'Pending'), ('processing', 'Processing'),
                 ('processed', 'Processed'), ('failed', 'Failed — review required')]


class TelegramUpdate(models.Model):
    update_id = models.BigIntegerField(unique=True)
    payload = models.JSONField()
    status = models.CharField(max_length=15, choices=WORK_STATUSES, default='pending', db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)


class NotificationDelivery(models.Model):
    deduplication_key = models.CharField(max_length=160, unique=True)
    chat_id = models.BigIntegerField()
    text = models.TextField()
    parse_mode = models.CharField(max_length=20, blank=True)
    broadcast = models.ForeignKey('accounts.BroadcastMessage', null=True, blank=True,
                                  on_delete=models.CASCADE, related_name='deliveries')
    exam_notification = models.ForeignKey('exams.ExamNotificationLog', null=True, blank=True,
                                          on_delete=models.CASCADE, related_name='deliveries')
    status = models.CharField(max_length=15, choices=WORK_STATUSES, default='pending', db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)


class QuestionExtraction(models.Model):
    inbox = models.OneToOneField('content.FileInbox', on_delete=models.CASCADE, related_name='question_extraction')
    source_hash = models.CharField(max_length=64, db_index=True)
    version = models.CharField(max_length=80)
    source_text = models.TextField()
    chunks = models.JSONField(default=dict)
    questions = models.JSONField(default=list)
    status = models.CharField(max_length=15, choices=WORK_STATUSES, default='pending', db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
