import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from telegram.ext import Application, MessageHandler, CommandHandler, filters

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the Telegram bot for file harvesting and student interaction'

    def handle(self, *args, **kwargs):
        from apps.bot.handlers import handle_channel_post, handle_start

        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))

        # Build application
        app = (
            Application.builder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Handle /start command from students
        app.add_handler(CommandHandler('start', handle_start))

        # Handle all channel posts
        app.add_handler(MessageHandler(
            filters.ChatType.CHANNEL & (filters.Document.ALL | filters.PHOTO),
            handle_channel_post,
        ))

        self.stdout.write(self.style.SUCCESS('Bot is running. Press Ctrl+C to stop.'))

        # Run directly without asyncio.run()
        app.run_polling(
            allowed_updates=['message', 'channel_post'],
            drop_pending_updates=False,
        )