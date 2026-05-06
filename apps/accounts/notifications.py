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




def send_telegram_message(chat_id, text: str, parse_mode: str | None = None) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning('Telegram notify skipped: TELEGRAM_BOT_TOKEN is not configured.')
        return False

    try:
        import httpx

        payload = {
            'chat_id': chat_id,
            'text': text,
        }
        if parse_mode:
            payload['parse_mode'] = parse_mode

        response = httpx.post(
            f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning('Telegram notify failed for chat %s: %s', chat_id, exc)
        return False


def notify_subscription_request_created(sub_request: SubscriptionRequest) -> bool:
    student = sub_request.student
    name = student.first_name or 'Student'

    text = (
        f'⏳ Payment Request Under Review\n\n'
        f'Hi {name}, your payment request for {sub_request.plan.name} '
        f'(Reference: {sub_request.reference}) is under review.\n\n'
        f'We will notify you once your payment is confirmed.'
    )
    return send_telegram_message(student.telegram_id, text)


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
    return send_telegram_message(student.telegram_id, text, parse_mode='Markdown')


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
    return send_telegram_message(student.telegram_id, text)


def broadcast_to_all_students(
    message: str,
    parse_mode: str | None = None,
    only_active: bool = True,
) -> tuple[int, int, int]:
    """
    Send `message` as a private Telegram DM to every student — exactly the
    same channel as subscription approval / rejection notifications.

    Returns (total, success_count, failed_count).
    """
    from .models import Student

    qs = Student.objects.all()
    if only_active:
        qs = qs.filter(is_active=True)

    telegram_ids = list(qs.values_list('telegram_id', flat=True))
    total   = len(telegram_ids)
    success = 0
    failed  = 0

    for tid in telegram_ids:
        if send_telegram_message(tid, message, parse_mode or None):
            success += 1
        else:
            failed += 1

    return total, success, failed

