from datetime import timedelta
from django.contrib import admin, messages
from django.utils import timezone
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from unfold.admin import ModelAdmin

from .models import Student, SubscriptionPlan, SubscriptionRequest, SiteSettings


# ─── Student Admin ─────────────────────────────────────────────────────────────

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
            return f'✅ Premium ({obj.days_remaining}d left)'
        return '⬜ Free'

    @admin.action(description='Activate Premium — 120 days (Semester Pass)')
    def activate_premium_120_days(self, request, queryset):
        for student in queryset:
            student.activate_premium(120)
        self.message_user(request, f'Activated 120-day premium for {queryset.count()} student(s).')

    @admin.action(description='Activate Premium — 90 days (Exit Exam Pass)')
    def activate_premium_90_days(self, request, queryset):
        for student in queryset:
            student.activate_premium(90)
        self.message_user(request, f'Activated 90-day premium for {queryset.count()} student(s).')

    @admin.action(description='Activate Premium — 365 days (Full Year Pass)')
    def activate_premium_365_days(self, request, queryset):
        for student in queryset:
            student.activate_premium(365)
        self.message_user(request, f'Activated 365-day premium for {queryset.count()} student(s).')

    @admin.action(description='Deactivate Premium')
    def deactivate_premium(self, request, queryset):
        queryset.update(
            subscription_status=Student.SUBSCRIPTION_FREE,
            subscription_expiry=None,
        )
        self.message_user(request, f'Deactivated premium for {queryset.count()} student(s).')


# ─── Subscription Request Admin ────────────────────────────────────────────────

@admin.register(SubscriptionRequest)
class SubscriptionRequestAdmin(ModelAdmin):
    list_display = [
        'reference',
        'student_display',
        'plan',
        'amount',
        'payment_method',
        'paid_from',
        'status_badge',
        'requested_at',
        'activated_by',
    ]
    list_filter = [
        'status',
        'payment_method',
        'plan',
    ]
    search_fields = [
        'reference',
        'student__username',
        'student__first_name',
        'student__telegram_id',
        'paid_from',
    ]
    readonly_fields = [
        'reference',
        'student',
        'plan',
        'amount',
        'payment_method',
        'paid_from',
        'requested_at',
        'updated_at',
        'activated_by',
        'activated_at',
    ]
    fieldsets = (
        ('Request Info', {
            'fields': (
                'reference',
                'student',
                'plan',
                'amount',
            )
        }),
        ('Payment Details', {
            'description': 'Verify these details against your Telebirr or CBE transaction history.',
            'fields': (
                'payment_method',
                'paid_from',
            )
        }),
        ('Decision', {
            'fields': (
                'status',
                'admin_note',
            )
        }),
        ('Activation', {
            'fields': (
                'activated_by',
                'activated_at',
            )
        }),
        ('Timestamps', {
            'fields': (
                'requested_at',
                'updated_at',
            )
        }),
    )
    actions = [
        'approve_requests',
        'reject_requests',
    ]
    ordering = ['-requested_at']

    # Show pending first in list
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # pending first, then by date
        from django.db.models import Case, When, IntegerField
        return qs.annotate(
            status_order=Case(
                When(status='pending',  then=0),
                When(status='approved', then=1),
                When(status='rejected', then=2),
                default=3,
                output_field=IntegerField(),
            )
        ).order_by('status_order', '-requested_at')

    @admin.display(description='Student')
    def student_display(self, obj):
        return str(obj.student)

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.status == SubscriptionRequest.STATUS_PENDING:
            return '🟡 Pending'
        if obj.status == SubscriptionRequest.STATUS_APPROVED:
            return '✅ Approved'
        return '❌ Rejected'

    @admin.action(description='✅ Approve & activate selected requests')
    def approve_requests(self, request, queryset):
        pending = queryset.filter(status=SubscriptionRequest.STATUS_PENDING)
        activated = 0

        for sub_request in pending:
            _approve_subscription_request(sub_request, request.user)
            activated += 1

        if activated:
            self.message_user(
                request,
                f'✅ Approved and activated premium for {activated} student(s). '
                f'Telegram notifications sent.',
                messages.SUCCESS,
            )
        already_done = queryset.count() - activated
        if already_done:
            self.message_user(
                request,
                f'{already_done} request(s) were already processed — skipped.',
                messages.WARNING,
            )

    @admin.action(description='❌ Reject selected requests')
    def reject_requests(self, request, queryset):
        pending = queryset.filter(status=SubscriptionRequest.STATUS_PENDING)
        count   = pending.count()
        for sub_request in pending:
            sub_request.status = SubscriptionRequest.STATUS_REJECTED
            sub_request.save(update_fields=['status', 'updated_at'])
            _notify_student_rejected(sub_request)
        self.message_user(request, f'❌ Rejected {count} request(s).')

    # ── Override save to auto-approve when admin changes status to approved ───

    def save_model(self, request, obj, form, change):
        if change and obj.status == SubscriptionRequest.STATUS_APPROVED:
            if not obj.activated_at:
                _approve_subscription_request(obj, request.user)
                self.message_user(
                    request,
                    f'✅ Subscription activated for {obj.student}. Telegram notification sent.',
                    messages.SUCCESS,
                )
                return  # already saved inside helper
        super().save_model(request, obj, form, change)


# ─── Subscription Plan Admin ───────────────────────────────────────────────────

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ModelAdmin):
    list_display = [
        'name',
        'plan_id',
        'price',
        'days',
        'badge',
        'is_active',
        'updated_at',
    ]
    list_editable = ['price', 'days', 'is_active']
    fields = [
        'plan_id',
        'name',
        'price',
        'days',
        'description',
        'badge',
        'is_active',
    ]


# ─── Site Settings Admin ───────────────────────────────────────────────────────

@admin.register(SiteSettings)
class SiteSettingsAdmin(ModelAdmin):
    list_display = ['telebirr_number', 'telebirr_name', 'cbe_account', 'updated_at']
    fieldsets = (
        ('Telebirr', {
            'description': 'Students will send payment to this Telebirr number.',
            'fields': (
                'telebirr_number',
                'telebirr_name',
            )
        }),
        ('CBE Bank (Optional)', {
            'description': 'Leave blank if you do not accept CBE transfers.',
            'fields': (
                'cbe_account',
                'cbe_name',
            )
        }),
        ('Instructions', {
            'fields': (
                'payment_instructions',
            )
        }),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _approve_subscription_request(sub_request: SubscriptionRequest, admin_user):
    """Activate premium on the student and mark the request as approved."""
    sub_request.student.activate_premium(sub_request.plan.days)

    sub_request.status       = SubscriptionRequest.STATUS_APPROVED
    sub_request.activated_by = admin_user
    sub_request.activated_at = timezone.now()
    sub_request.save(update_fields=[
        'status', 'activated_by', 'activated_at', 'updated_at'
    ])

    _notify_student_approved(sub_request)


def _notify_student_approved(sub_request: SubscriptionRequest):
    """Send Telegram notification to student on approval."""
    try:
        from django.conf import settings
        import requests as http_requests

        student  = sub_request.student
        days     = sub_request.plan.days
        expiry   = student.subscription_expiry.strftime('%B %d, %Y')
        name     = student.first_name or 'Student'

        text = (
            f"🎉 *Premium Activated!*\n\n"
            f"Hi {name}, your payment has been verified and your premium subscription is now active.\n\n"
            f"📦 *Plan:* {sub_request.plan.name}\n"
            f"📅 *Valid until:* {expiry}\n"
            f"🔑 *Reference:* `{sub_request.reference}`\n\n"
            f"You now have full access to all study materials and exit exam questions. Good luck! 🚀"
        )

        http_requests.post(
            f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
            json={
                'chat_id':    student.telegram_id,
                'text':       text,
                'parse_mode': 'Markdown',
            },
            timeout=10,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'Telegram notify failed for approval: {e}')


def _notify_student_rejected(sub_request: SubscriptionRequest):
    """Send Telegram notification to student on rejection."""
    try:
        from django.conf import settings
        import requests as http_requests

        student = sub_request.student
        name    = student.first_name or 'Student'

        text = (
            f"❌ *Payment Not Verified*\n\n"
            f"Hi {name}, unfortunately we could not verify your payment for "
            f"*{sub_request.plan.name}* (Reference: `{sub_request.reference}`).\n\n"
            f"Please make sure you:\n"
            f"• Sent to the correct Telebirr number\n"
            f"• Included your reference code in the payment note\n\n"
            f"Contact support if you believe this is a mistake."
        )

        http_requests.post(
            f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
            json={
                'chat_id':    student.telegram_id,
                'text':       text,
                'parse_mode': 'Markdown',
            },
            timeout=10,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'Telegram notify failed for rejection: {e}')