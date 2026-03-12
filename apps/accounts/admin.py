from django.contrib import admin
from datetime import timedelta
from django.utils import timezone
from unfold.admin import ModelAdmin
from .models import Student


@admin.register(Student)
class StudentAdmin(ModelAdmin):
    list_display = [
        'display_name',
        'telegram_id',
        'preferred_department',
        'preferred_program',
        'preferred_year',
        'subscription_badge',
        'days_remaining',
        'downloads_today',
        'joined_at',
    ]
    list_filter = [
        'subscription_status',
        'preferred_program',
        'preferred_year',
        'onboarding_complete',
        'is_active',
    ]
    search_fields = [
        'first_name',
        'last_name',
        'username',
        'telegram_id',
    ]
    readonly_fields = [
        'telegram_id',
        'joined_at',
        'updated_at',
        'is_premium',
        'days_remaining',
    ]
    fieldsets = (
        ('Telegram Identity', {
            'fields': (
                'telegram_id',
                'first_name',
                'last_name',
                'username',
            )
        }),
        ('Subscription', {
            'fields': (
                'subscription_status',
                'subscription_expiry',
                'is_premium',
                'days_remaining',
            )
        }),
        ('Onboarding Preferences', {
            'fields': (
                'onboarding_complete',
                'preferred_department',
                'preferred_program',
                'preferred_year',
                'preferred_period',
            )
        }),
        ('Usage', {
            'fields': (
                'downloads_today',
                'last_download_reset',
                'is_active',
            )
        }),
        ('Timestamps', {
            'fields': (
                'joined_at',
                'updated_at',
            )
        }),
    )
    actions = [
        'activate_premium_120_days',
        'activate_premium_90_days',
        'activate_premium_365_days',
        'deactivate_premium',
    ]

    @admin.display(description='Student')
    def display_name(self, obj):
        if obj.username:
            return f'@{obj.username}'
        return f'{obj.first_name} {obj.last_name}'.strip()

    @admin.display(description='Subscription')
    def subscription_badge(self, obj):
        if obj.is_premium:
            return '✅ Premium'
        return '⬜ Free'

    @admin.action(description='Activate Premium — 120 days (Semester Pass)')
    def activate_premium_120_days(self, request, queryset):
        self._activate_premium(queryset, 120)
        self.message_user(request, f'Activated 120-day premium for {queryset.count()} student(s).')

    @admin.action(description='Activate Premium — 90 days (Exit Exam Pass)')
    def activate_premium_90_days(self, request, queryset):
        self._activate_premium(queryset, 90)
        self.message_user(request, f'Activated 90-day premium for {queryset.count()} student(s).')

    @admin.action(description='Activate Premium — 365 days (Full Year Pass)')
    def activate_premium_365_days(self, request, queryset):
        self._activate_premium(queryset, 365)
        self.message_user(request, f'Activated 365-day premium for {queryset.count()} student(s).')

    @admin.action(description='Deactivate Premium')
    def deactivate_premium(self, request, queryset):
        queryset.update(
            subscription_status=Student.SUBSCRIPTION_FREE,
            subscription_expiry=None,
        )
        self.message_user(request, f'Deactivated premium for {queryset.count()} student(s).')

    def _activate_premium(self, queryset, days):
        expiry = timezone.now() + timedelta(days=days)
        queryset.update(
            subscription_status=Student.SUBSCRIPTION_PREMIUM,
            subscription_expiry=expiry,
        )