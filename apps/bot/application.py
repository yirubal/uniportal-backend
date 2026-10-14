"""Telegram handler application owned by the worker, never initialized by web."""

import logging

from django.conf import settings
from telegram import BotCommand, Update

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    BotCommand('start', 'Open UniPortal'),
    BotCommand('help', 'How to use the portal'),
    BotCommand('status', 'Check your subscription'),
)

async def process_telegram_update(update_data):
    """One worker subprocess owns initialization, processing, and shutdown."""
    app = _build_application()
    errors = []

    async def record_error(update, context):
        errors.append(context.error)

    app.add_error_handler(record_error)
    async with app:
        update = Update.de_json(update_data, app.bot)
        await app.process_update(update)
        if errors:
            raise errors[0]


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

    app.add_handler(CallbackQueryHandler(handle_callback_query))

    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & (filters.Document.ALL | filters.PHOTO),
        handle_channel_post,
    ))

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_unknown_message,
    ))

    logger.info('Bot application initialized in webhook mode')
    return app
