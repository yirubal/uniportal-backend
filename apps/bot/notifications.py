from django.conf import settings


def send_admin_notification(message, *, deduplication_key=None):
    from apps.accounts.notifications import send_telegram_message
    if not settings.TELEGRAM_ADMIN_CHAT_ID:
        return False
    return send_telegram_message(settings.TELEGRAM_ADMIN_CHAT_ID, message, parse_mode='HTML',
                                 deduplication_key=deduplication_key)
