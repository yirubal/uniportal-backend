"""
Singleton bot Application instance shared across webhook requests.

The handlers are the same handlers previously registered by run_bot.py; only
the update delivery mechanism changes from polling to webhook.
"""

import logging
import threading

from django.conf import settings
from telegram import BotCommand, Update

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    BotCommand('start', 'Open the student portal'),
    BotCommand('help', 'Show help and support information'),
    BotCommand('status', 'Check your subscription status'),
    BotCommand('exam', 'Check your exam schedule and room'),
)

_application = None
_initialized = False
_initialize_lock = threading.Lock()


def get_application():
    """
    Returns the singleton bot Application.
    Creates it on first call.
    """
    global _application
    if _application is None:
        _application = _build_application()
    return _application


async def initialize_application():
    """
    Ensure the PTB Application is initialized before processing webhooks.
    """
    global _initialized

    app = get_application()
    if _initialized:
        return app

    with _initialize_lock:
        if not _initialized:
            await app.initialize()
            _initialized = True

    return app


async def process_telegram_update(update_data):
    """
    Convert a Telegram webhook payload into an Update and process it.
    """
    app = await initialize_application()
    update = Update.de_json(update_data, app.bot)
    await app.process_update(update)


async def set_visible_bot_commands(bot_or_application):
    """
    Register the bot command menu shown by Telegram clients.
    """
    bot = getattr(bot_or_application, 'bot', bot_or_application)
    await bot.set_my_commands(BOT_COMMANDS)


def _build_application():
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )
    from apps.bot.handlers import (
        handle_callback_query,
        handle_channel_post,
        handle_exam,
        handle_exam_lookup_response,
        handle_help,
        handle_start,
        handle_status,
        handle_unknown_message,
    )

    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .read_timeout(10)
        .write_timeout(10)
        .connect_timeout(10)
        .pool_timeout(10)
        .updater(None)
        .build()
    )

    app.add_handler(CommandHandler('start', handle_start))
    app.add_handler(CommandHandler('help', handle_help))
    app.add_handler(CommandHandler('status', handle_status))
    app.add_handler(CommandHandler('exam', handle_exam))

    app.add_handler(CallbackQueryHandler(handle_callback_query))

    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & (filters.Document.ALL | filters.PHOTO),
        handle_channel_post,
    ))

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_exam_lookup_response,
    ), group=0)

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_unknown_message,
    ), group=1)

    logger.info('Bot application initialized in webhook mode')
    return app
