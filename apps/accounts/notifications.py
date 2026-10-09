import logging

from django.conf import settings

from .models import SubscriptionRequest

logger = logging.getLogger(__name__)


def check_channel_membership_sync(user_id: int) -> bool:
    """
    Synchronous check: returns True if user_id is a member/admin/creator of
    the configured Telegram channel. Fails open (returns True) on any error so
    users are never accidentally blocked by an API hiccup.
    """
    channel_id = getattr(settings, 'TELEGRAM_OFFICIAL_CHANNEL_ID', '')
    if not channel_id:
        return True  # Gate not configured — let everyone through

    try:
        import httpx
        response = httpx.get(
            f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChatMember',
            params={'chat_id': channel_id, 'user_id': user_id},
            timeout=5,
        )
        data = response.json()
        member_status = data.get('result', {}).get('status', 'left')
        return member_status in ('member', 'administrator', 'creator')
    except Exception as exc:
        logger.warning('Channel membership check failed for user %s: %s — failing open', user_id, exc)
        return True  # Never block users due to API errors




def send_telegram_message(chat_id, text, parse_mode=None, *, deduplication_key=None, broadcast=None, exam_notification=None):
    """Persist delivery intent. Only the worker calls Telegram."""
    from uuid import uuid4
    from apps.bot.models import NotificationDelivery
    if not text or len(text) > 4096:
        raise ValueError('Telegram messages must contain 1–4096 characters.')
    NotificationDelivery.objects.get_or_create(
        deduplication_key=deduplication_key or f'message:{uuid4()}',
        defaults={'chat_id': int(chat_id), 'text': text, 'parse_mode': parse_mode or '',
                  'broadcast': broadcast, 'exam_notification': exam_notification},
    )
    return True


def notify_subscription_request_created(sub_request: SubscriptionRequest) -> bool:
    student = sub_request.student
    name = student.first_name or 'Student'

    text = (
        f'⏳ Payment Request Under Review\n\n'
        f'Hi {name}, your payment request for {sub_request.plan.name} '
        f'(Reference: {sub_request.reference}) is under review.\n\n'
        f'We will notify you once your payment is confirmed.'
    )
    return send_telegram_message(student.telegram_id, text, deduplication_key=f'payment:{sub_request.pk}:{sub_request.status}:student')


def notify_subscription_approved(sub_request: SubscriptionRequest) -> bool:
    student = sub_request.student
    expiry = student.subscription_expiry.strftime('%B %d, %Y')
    name = student.first_name or 'Student'

    text = (
        f"🎉 *Premium Activated!*\n\n"
        f"Hi {name}, your payment has been verified and your premium subscription is now active.\n\n"
        f"📦 *Plan:* {sub_request.plan.name}\n"
        f"📅 *Valid until:* {expiry}\n"
        f"🔑 *Reference:* `{sub_request.reference}`\n\n"
        f"You now have full access to all study materials and exit exam questions. Good luck! 🚀"
    )
    return send_telegram_message(student.telegram_id, text, parse_mode='Markdown',
                                 deduplication_key=f'payment:{sub_request.pk}:approved:student')


def notify_subscription_rejected(sub_request: SubscriptionRequest) -> bool:
    student = sub_request.student
    name = student.first_name or 'Student'

    text = (
        f"❌ Payment Not Verified\n\n"
        f"Hi {name}, unfortunately we could not verify your payment for "
        f"{sub_request.plan.name} (Reference: {sub_request.reference}).\n\n"
        f"Please make sure you:\n"
        f"• Sent to the correct Telebirr number\n"
        f"• Included your reference code in the payment note\n\n"
        f"Contact support if you believe this is a mistake."
    )
    return send_telegram_message(student.telegram_id, text, deduplication_key=f'payment:{sub_request.pk}:{sub_request.status}:student')


def queue_broadcast(message, parse_mode='', sent_by=None):
    from django.db import transaction
    from .models import BroadcastMessage, Student
    from apps.bot.models import NotificationDelivery
    if not message or len(message) > 4096:
        raise ValueError('Broadcasts must contain 1–4096 characters.')
    if parse_mode not in {'', 'Markdown', 'HTML'}:
        raise ValueError('Unsupported Telegram formatting mode.')
    with transaction.atomic():
        broadcast = BroadcastMessage.objects.create(message=message, parse_mode=parse_mode, sent_by=sent_by)
        batch = []
        total = 0
        for chat_id in Student.objects.filter(is_active=True).values_list('telegram_id', flat=True).iterator(chunk_size=500):
            batch.append(NotificationDelivery(
                deduplication_key=f'broadcast:{broadcast.pk}:{chat_id}', chat_id=chat_id,
                text=message, parse_mode=parse_mode, broadcast=broadcast,
            ))
            total += 1
            if len(batch) == 500:
                NotificationDelivery.objects.bulk_create(batch)
                batch = []
        if batch:
            NotificationDelivery.objects.bulk_create(batch)
        broadcast.total_users = total
        broadcast.save(update_fields=['total_users'])
    return broadcast
