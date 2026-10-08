from django.db import transaction
from django.utils import timezone

from .models import Student, SubscriptionRequest
from .notifications import notify_subscription_approved, notify_subscription_rejected


def approve_subscription_request(request_id, admin_user):
    """Serialize renewals for a student and grant each pending payment once."""
    student_id = SubscriptionRequest.objects.values_list('student_id', flat=True).get(pk=request_id)
    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student_id)
        sub_request = SubscriptionRequest.objects.select_for_update().get(pk=request_id)
        if sub_request.student_id != student_id:
            raise ValueError('The request student changed; reload before approving.')
        if sub_request.status != SubscriptionRequest.STATUS_PENDING:
            return False
        days = sub_request.plan.days
        if days <= 0:
            raise ValueError('Subscription duration must be positive.')
        student.activate_premium(days)
        sub_request.student = student
        sub_request.status = SubscriptionRequest.STATUS_APPROVED
        sub_request.activated_by = admin_user
        sub_request.activated_at = timezone.now()
        sub_request.save(update_fields=['status', 'activated_by', 'activated_at', 'updated_at'])
        transaction.on_commit(lambda: notify_subscription_approved(sub_request), robust=True)
    return True


def reject_subscription_request(request_id):
    """Only pending payments may be rejected; granted access is never revoked."""
    with transaction.atomic():
        sub_request = SubscriptionRequest.objects.select_for_update().get(pk=request_id)
        if sub_request.status != SubscriptionRequest.STATUS_PENDING:
            return False
        sub_request.status = SubscriptionRequest.STATUS_REJECTED
        sub_request.save(update_fields=['status', 'updated_at'])
        transaction.on_commit(lambda: notify_subscription_rejected(sub_request), robust=True)
    return True
