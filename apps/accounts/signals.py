import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import SubscriptionRequest

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=SubscriptionRequest)
def subscription_request_deleted(sender, instance, **kwargs):
    """
    Deleting a payment-review record must not grant or revoke premium access.
    Premium state changes are owned by the explicit admin approve/reject actions.
    """
    logger.info(
        'SubscriptionRequest %s deleted for student %s with status %s; '
        'student subscription status left unchanged.',
        instance.reference,
        instance.student_id,
        instance.status,
    )
