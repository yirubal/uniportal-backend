import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the Telegram bot for file harvesting and student interaction'

    def handle(self, *args, **kwargs):
        from apps.bot.handlers import (
            handle_channel_post,
            handle_start,
            handle_help,
            handle_status,
            handle_unknown_message,
            handle_callback_query,
        )

        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))

        app = (
            Application.builder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # ── Student commands ──────────────────────────────────────────────────
        app.add_handler(CommandHandler('start',  handle_start))
        app.add_handler(CommandHandler('help',   handle_help))
        app.add_handler(CommandHandler('status', handle_status))

        # ── Inline button callbacks ───────────────────────────────────────────
        app.add_handler(CallbackQueryHandler(handle_callback_query))

        # ── Channel file harvesting ───────────────────────────────────────────
        app.add_handler(MessageHandler(
            filters.ChatType.CHANNEL & (filters.Document.ALL | filters.PHOTO),
            handle_channel_post,
        ))

        # ── Unknown messages from students ────────────────────────────────────
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.ALL,
            handle_unknown_message,
        ))

        self.stdout.write(self.style.SUCCESS(
            'Bot is running.\n'
            'Commands: /start  /help  /status\n'
            'Press Ctrl+C to stop.'
        ))

        app.run_polling(
            allowed_updates=['message', 'channel_post', 'callback_query'],
            drop_pending_updates=False,
            poll_interval=2.0,
            timeout=10,
            read_timeout=10,
            write_timeout=10,
            connect_timeout=10,
        )