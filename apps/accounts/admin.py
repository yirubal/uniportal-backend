from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from django.db import transaction
from unfold.admin import ModelAdmin

from django.shortcuts import render, redirect

from .models import Student, SubscriptionPlan, SubscriptionRequest, SiteSettings, BroadcastMessage
from .notifications import queue_broadcast
from .forms import BroadcastForm
from .services import approve_subscription_request, reject_subscription_request


# ─── Student Admin ─────────────────────────────────────────────────────────────

@admin.register(Student)
class StudentAdmin(ModelAdmin):
    list_select_related = ['preferred_department']
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
        'subscription_status',
        'subscription_expiry',
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
        'deactivate_premium',
    ]

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom = [
            path('broadcast/status/', self.admin_site.admin_view(self.broadcast_status_view), name='accounts_broadcast_status'),
            path(
                'broadcast/',
                self.admin_site.admin_view(self.broadcast_view),
                name='accounts_broadcast',
            ),
        ]
        return custom + urls

    def broadcast_history(self, request):
        queryset = BroadcastMessage.objects.select_related('sent_by')
        if not self.admin_site._registry[BroadcastMessage].has_view_or_change_permission(request):
            queryset = queryset.filter(sent_by=request.user)
        return queryset.order_by('-sent_at', '-pk')[:10]

    def broadcast_status_view(self, request):
        from django.http import JsonResponse
        if not (request.user.has_perm('accounts.add_broadcastmessage')
                or self.admin_site._registry[BroadcastMessage].has_view_or_change_permission(request)):
            raise PermissionDenied
        return JsonResponse({'broadcasts': [{
            'id': broadcast.pk, 'total': broadcast.total_users, 'delivered': broadcast.success_count,
            'pending': broadcast.pending_count, 'failed': broadcast.failed_count,
        } for broadcast in self.broadcast_history(request)]})

    def broadcast_view(self, request):
        if not request.user.has_perm('accounts.add_broadcastmessage'):
            raise PermissionDenied
        form = BroadcastForm(request.POST if request.method == 'POST' else None, user=request.user)
        if request.method == 'POST' and form.is_valid():
            try:
                broadcast = queue_broadcast(form.cleaned_data['message'], form.cleaned_data['parse_mode'], request.user,
                                            submission_token=form.cleaned_data['submission_token'])
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(request, f'Broadcast #{broadcast.pk} is queued for {broadcast.total_users} student(s). Repeated submissions use the same broadcast.', messages.SUCCESS)
                return redirect('admin:accounts_broadcast')
        context = {
            **self.admin_site.each_context(request), 'title': 'Send Broadcast Message',
            'opts': Student._meta, 'form': form, 'recent_broadcasts': self.broadcast_history(request),
            'parse_mode_choices': BroadcastMessage.PARSE_CHOICES,
            'recipient_count': Student.objects.filter(is_active=True).count(),
            'can_view_deliveries': request.user.has_perm('bot.view_notificationdelivery') or request.user.has_perm('bot.change_notificationdelivery'),
        }
        return render(request, 'admin/accounts/broadcast.html', context)


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

    @admin.action(permissions=['change'], description='Deactivate Premium')
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
        'payment_reference',
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
        'payment_reference',
    ]
    readonly_fields = [
        'reference',
        'student',
        'plan',
        'amount',
        'payment_method',
        'payment_reference',
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
                'payment_reference',
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
        qs = super().get_queryset(request).select_related('student', 'plan', 'activated_by')
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

    @admin.action(permissions=['change'], description='✅ Approve & activate selected requests')
    def approve_requests(self, request, queryset):
        activated = 0
        selected_ids = list(queryset.values_list('pk', flat=True))
        for request_id in selected_ids:
            if approve_subscription_request(request_id, request.user):
                activated += 1

        if activated:
            self.message_user(
                request,
                f'✅ Approved and activated premium for {activated} student(s). '
                f'Telegram notifications queued for the worker.',
                messages.SUCCESS,
            )
        already_done = len(selected_ids) - activated
        if already_done:
            self.message_user(
                request,
                f'{already_done} request(s) were already processed — skipped.',
                messages.WARNING,
            )

    @admin.action(permissions=['change'], description='❌ Reject selected requests')
    def reject_requests(self, request, queryset):
        selected_ids = list(queryset.values_list('pk', flat=True))
        rejected = sum(reject_subscription_request(request_id) for request_id in selected_ids)
        skipped = len(selected_ids) - rejected
        self.message_user(
            request,
            f'Rejected {rejected} pending request(s); skipped {skipped} already processed request(s). '
            'Approved payments and their granted access are preserved. '
            'Notifications are queued for the worker.',
            messages.SUCCESS if rejected else messages.WARNING,
        )

    # ── Keep admin detail saves from bypassing the approve action ─────────────

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = (
                SubscriptionRequest.objects.select_for_update()
                .filter(id=obj.id)
                .values_list('status', flat=True)
                .first()
            )

        if (
            change
            and obj.status == SubscriptionRequest.STATUS_APPROVED
            and previous_status != SubscriptionRequest.STATUS_APPROVED
        ):
            obj.status = previous_status or SubscriptionRequest.STATUS_PENDING
            self.message_user(
                request,
                'Use the "Approve & activate selected requests" action to activate premium. '
                'Direct status edits do not grant access.',
                messages.WARNING,
            )
        if (
            change
            and obj.status == SubscriptionRequest.STATUS_REJECTED
            and previous_status != SubscriptionRequest.STATUS_REJECTED
        ):
            rejected = reject_subscription_request(obj.pk)
            obj.refresh_from_db()
            self.message_user(
                request,
                'Pending request rejected; notification queued for the worker.' if rejected
                else 'Only pending payments can be rejected. Approved payments are preserved.',
                messages.SUCCESS if rejected else messages.WARNING,
            )
            return
        if change and obj.status != previous_status:
            obj.status = previous_status
            self.message_user(request, 'Use the approve/reject actions to change payment status.', messages.WARNING)
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

# ─── Broadcast Message Admin (read-only log) ──────────────────────────────────

@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(ModelAdmin):
    search_fields = ['message']
    list_select_related = ['sent_by']
    list_display  = ['truncated_message', 'sent_by', 'sent_at', 'total_users', 'success_count', 'failed_count']
    readonly_fields = ['message', 'parse_mode', 'sent_by', 'sent_at', 'total_users', 'success_count', 'failed_count']
    ordering      = ['-sent_at']

    def has_add_permission(self, request):    return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    @admin.display(description='Message')
    def truncated_message(self, obj):
        return obj.message[:80] + '…' if len(obj.message) > 80 else obj.message


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
