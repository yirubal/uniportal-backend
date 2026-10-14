"""Subscriptions API endpoints."""
import re
from django.db import transaction
from django.utils.html import escape
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from ..throttles import SubscriptionRateThrottle
from apps.accounts.models import Student
from ..serializers import SubscriptionRequestInputSerializer
from ..permissions import IsTelegramAuthenticated

PAYMENT_REFERENCE_RE = re.compile(r'^[A-Z0-9]{6,50}$')


class SubscriptionPlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.models import SubscriptionPlan
        plans = SubscriptionPlan.objects.filter(is_active=True)
        data  = [
            {
                'id':          p.plan_id,
                'name':        p.name,
                'price':       float(p.price),
                'days':        p.days,
                'description': p.description,
                'badge':       p.badge,
            }
            for p in plans
        ]
        return Response(data)


class SubscriptionRequestView(APIView):
    permission_classes = [IsTelegramAuthenticated]
    throttle_classes = [SubscriptionRateThrottle]

    def post(self, request):
        from uuid import uuid4
        from django.db import IntegrityError, transaction
        from apps.accounts.models import SiteSettings, SubscriptionPlan, SubscriptionRequest

        inputs = SubscriptionRequestInputSerializer(data=request.data)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        plan_id = params['plan']
        payment_method = params.get('payment_method') or 'telebirr'
        payment_reference = _normalize_payment_reference(
            params.get('payment_reference', params.get('paid_from', ''))
        )

        try:
            plan = SubscriptionPlan.objects.get(plan_id=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {'error': 'INVALID_PLAN', 'message': 'Invalid plan selected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payment_method not in dict(SubscriptionRequest.PAYMENT_CHOICES):
            return Response(
                {
                    'error': 'INVALID_PAYMENT_METHOD',
                    'message': 'Choose either Telebirr or CBE as the payment method.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = SubscriptionRequest.objects.filter(
            student=request.student,
            status=SubscriptionRequest.STATUS_PENDING,
        ).select_related('plan').first()

        if existing:
            return _build_payment_response(existing, existing.plan)

        settings_obj = SiteSettings.get()
        if payment_method == SubscriptionRequest.PAYMENT_CBE and not settings_obj.cbe_account:
            return Response(
                {
                    'error': 'PAYMENT_METHOD_UNAVAILABLE',
                    'message': 'CBE payment is not available right now. Please use Telebirr.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reference_error = _validate_payment_reference(payment_reference, payment_method)
        if reference_error:
            return Response(
                {
                    'error': 'INVALID_PAYMENT_REFERENCE',
                    'message': reference_error,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                Student.objects.select_for_update().get(pk=request.student.pk)
                existing = SubscriptionRequest.objects.filter(
                    student=request.student,
                    status=SubscriptionRequest.STATUS_PENDING,
                ).select_related('plan').first()

                if existing:
                    sub_request = existing
                else:
                    reference = 'UNI-' + uuid4().hex[:16].upper()

                    sub_request = SubscriptionRequest.objects.create(
                        student=request.student,
                        plan=plan,
                        reference=reference,
                        payment_method=payment_method,
                        paid_from=payment_reference,
                        payment_reference=payment_reference,
                        amount=plan.price,
                        status=SubscriptionRequest.STATUS_PENDING,
                    )
                    _notify_subscription_request_created(sub_request)
        except IntegrityError:
            sub_request = SubscriptionRequest.objects.filter(
                student=request.student,
                status=SubscriptionRequest.STATUS_PENDING,
            ).select_related('plan').first()
            if sub_request is None:
                raise

        return _build_payment_response(sub_request, sub_request.plan)

    def get(self, request):
        from apps.accounts.models import SubscriptionRequest, SiteSettings

        active_request = SubscriptionRequest.objects.filter(
            student=request.student,
            status__in=[
                SubscriptionRequest.STATUS_PENDING,
                SubscriptionRequest.STATUS_APPROVED,
                SubscriptionRequest.STATUS_REJECTED,
            ],
        ).select_related('plan').first()

        settings_obj = SiteSettings.get()

        return Response({
            'has_pending_request': (
                active_request is not None
                and active_request.status == SubscriptionRequest.STATUS_PENDING
            ),
            'pending_request': _serialize_subscription_request(active_request)
            if active_request and active_request.status == SubscriptionRequest.STATUS_PENDING
            else None,
            'current_request': _serialize_subscription_request(active_request),
            'active_request': _serialize_subscription_request(active_request),
            'payment_options': _build_payment_options(settings_obj),
            'additional_instructions': settings_obj.payment_instructions or '',
        })


def _serialize_subscription_request(sub_request):
    if not sub_request:
        return None

    return {
        'reference': sub_request.reference,
        'plan': sub_request.plan.name,
        'amount': float(sub_request.amount),
        'status': sub_request.status,
        'payment_method': sub_request.payment_method,
        'payment_reference': sub_request.payment_reference or sub_request.paid_from,
        'requested_at': sub_request.requested_at,
        'updated_at': sub_request.updated_at,
    }


def _notify_subscription_request_created(sub_request):
    from apps.accounts.notifications import notify_subscription_request_created
    from apps.bot.notifications import send_admin_notification

    notify_subscription_request_created(sub_request)

    send_admin_notification(_build_admin_subscription_request_message(sub_request),
                            deduplication_key=f'payment:{sub_request.pk}:pending:admin')


def _build_admin_subscription_request_message(sub_request):
    student = sub_request.student
    full_name = f'{student.first_name} {student.last_name}'.strip() or 'Student'
    username = f'@{student.username}' if student.username else 'No username'
    payment_reference = sub_request.payment_reference or sub_request.paid_from or 'Not provided'

    return (
        '💰 New Subscription Request\n\n'
        f'Student: {escape(full_name)} ({escape(username)})\n'
        f'Plan: {escape(sub_request.plan.name)} — ETB {sub_request.plan.price}\n'
        f'Payment: {escape(sub_request.payment_method)} from {escape(payment_reference)}\n'
        f'Reference: {escape(sub_request.reference)}\n'
        f'Amount: ETB {sub_request.amount}\n\n'
        '👉 Review: https://web-production-312b.up.railway.app/admin/accounts/subscriptionrequest/'
    )


def _build_payment_response(sub_request, plan):
    from apps.accounts.models import SiteSettings
    from rest_framework.response import Response

    settings_obj = SiteSettings.get()

    payment_options = _build_payment_options(settings_obj)

    return Response({
        'reference':               sub_request.reference,
        'plan':                    plan.name,
        'amount':                  float(sub_request.amount),
        'days':                    plan.days,
        'status':                  sub_request.status,
        'payment_method':          sub_request.payment_method,
        'payment_reference':       sub_request.payment_reference or sub_request.paid_from,
        'payment_destination':     _build_payment_destination(sub_request.payment_method, payment_options),
        'note':                    f'Include reference {sub_request.reference} in your payment note.',
        'additional_instructions': settings_obj.payment_instructions or '',
        'payment_options':         payment_options,
    })


def _normalize_payment_reference(raw_reference):
    return str(raw_reference or '').strip().upper()


def _build_payment_options(settings_obj):
    return {
        'telebirr': {
            'number': settings_obj.telebirr_number,
            'name': settings_obj.telebirr_name,
        },
        'cbe': {
            'account': settings_obj.cbe_account,
            'name': settings_obj.cbe_name,
        } if settings_obj.cbe_account else None,
    }


def _validate_payment_reference(payment_reference, payment_method):
    if not payment_reference:
        if payment_method == 'cbe':
            return 'Enter the CBE transaction ID from your receipt.'
        return 'Enter the Telebirr transaction number from your receipt.'

    if not PAYMENT_REFERENCE_RE.fullmatch(payment_reference):
        return 'Use 6-50 characters with capital letters and numbers only.'

    if not any(char.isalpha() for char in payment_reference):
        return 'The transaction reference must include at least one capital letter.'

    if not any(char.isdigit() for char in payment_reference):
        return 'The transaction reference must include at least one number.'

    return None


def _build_payment_destination(payment_method, payment_options):
    destination = payment_options.get(payment_method)
    if not destination:
        return None

    if payment_method == 'cbe':
        return {
            'method': 'cbe',
            'label': 'CBE account number',
            'value': destination['account'],
            'name': destination['name'],
        }

    return {
        'method': 'telebirr',
        'label': 'Telebirr number',
        'value': destination['number'],
        'name': destination['name'],
    }
