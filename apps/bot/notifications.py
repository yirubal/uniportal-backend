import asyncio
import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


async def _send_admin_notification(message: str):
    from telegram import Bot

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
        text=message,
        parse_mode='HTML',
    )


def _run_admin_notification(message: str):
    try:
        asyncio.run(_send_admin_notification(message))
    except Exception as exc:
        logger.error('Failed to send admin notification: %s', exc)


def send_admin_notification(message: str):
    """
    Fire-and-forget Telegram admin notification.

    Safe from synchronous Django views and from environments that already have
    a running event loop. It never raises back to the caller.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ADMIN_CHAT_ID:
        logger.warning(
            'Admin notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID is not configured.'
        )
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        thread = threading.Thread(
            target=_run_admin_notification,
            args=(message,),
            daemon=True,
        )
        thread.start()
        return

    try:
        loop.create_task(_send_admin_notification(message))
    except Exception as exc:
        logger.error('Failed to schedule admin notification: %s', exc)
