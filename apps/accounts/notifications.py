import logging

from django.conf import settings

from .models import SubscriptionRequest

logger = logging.getLogger(__name__)


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
    text = (
        'Your payment request is under review. '
        'We will notify you once your payment is confirmed.'
    )
    return send_telegram_message(sub_request.student.telegram_id, text)


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
