from datetime import timedelta
from django.contrib import admin, messages
from django.utils import timezone
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from unfold.admin import ModelAdmin

from .models import Student, SubscriptionPlan, SubscriptionRequest, SiteSettings
from .notifications import notify_subscription_approved, notify_subscription_rejected


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
        rejectable_requests = list(
            queryset
            .filter(status__in=[
                SubscriptionRequest.STATUS_PENDING,
                SubscriptionRequest.STATUS_APPROVED,
            ])
            .select_related('student', 'plan')
        )
        count = len(rejectable_requests)

        for sub_request in rejectable_requests:
            _reject_subscription_request(sub_request)

        skipped = queryset.count() - count
        if count:
            self.message_user(request, f'❌ Rejected {count} subscription request(s).', messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f'{skipped} selected request(s) were already rejected — skipped.',
                messages.WARNING,
            )

    # ── Override save to auto-approve when admin changes status to approved ───

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = (
                SubscriptionRequest.objects
                .filter(id=obj.id)
                .values_list('status', flat=True)
                .first()
            )

        if change and obj.status == SubscriptionRequest.STATUS_APPROVED:
            if not obj.activated_at:
                _approve_subscription_request(obj, request.user)
                self.message_user(
                    request,
                    f'✅ Subscription activated for {obj.student}. Telegram notification sent.',
                    messages.SUCCESS,
                )
                return  # already saved inside helper
        if (
            change
            and obj.status == SubscriptionRequest.STATUS_REJECTED
            and previous_status != SubscriptionRequest.STATUS_REJECTED
        ):
            _reject_subscription_request(obj)
            self.message_user(
                request,
                f'❌ Subscription request rejected for {obj.student}. Telegram notification sent.',
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

    notify_subscription_approved(sub_request)


def _reject_subscription_request(sub_request: SubscriptionRequest):
    """Mark a request rejected and roll back premium if this was its only approval."""
    was_approved = sub_request.status == SubscriptionRequest.STATUS_APPROVED

    sub_request.status = SubscriptionRequest.STATUS_REJECTED
    sub_request.activated_by = None
    sub_request.activated_at = None
    sub_request.save(update_fields=[
        'status', 'activated_by', 'activated_at', 'updated_at'
    ])

    if was_approved:
        has_other_approved = SubscriptionRequest.objects.filter(
            student=sub_request.student,
            status=SubscriptionRequest.STATUS_APPROVED,
        ).exclude(id=sub_request.id).exists()

        if not has_other_approved:
            sub_request.student.subscription_status = Student.SUBSCRIPTION_FREE
            sub_request.student.subscription_expiry = None
            sub_request.student.save(update_fields=[
                'subscription_status', 'subscription_expiry'
            ])

    notify_subscription_rejected(sub_request)
