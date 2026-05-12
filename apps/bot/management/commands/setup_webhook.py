"""
Registers the Telegram webhook.

Run once after deployment:
    python manage.py setup_webhook

To remove webhook:
    python manage.py setup_webhook --delete
"""

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Registers or removes the Telegram webhook'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Remove the webhook',
        )

    def handle(self, *args, **options):
        asyncio.run(self._run(options['delete']))

    async def _run(self, delete: bool):
        from telegram import Bot
        from apps.bot.application import set_visible_bot_commands

        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError('TELEGRAM_BOT_TOKEN is not configured')

        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        webhook_url = settings.TELEGRAM_WEBHOOK_URL
        allowed_updates = ['message', 'channel_post', 'callback_query']

        if delete:
            await bot.delete_webhook(drop_pending_updates=True)
            self.stdout.write(self.style.SUCCESS('✅ Webhook deleted. Bot is now in polling mode.'))
            return

        await set_visible_bot_commands(bot)

        webhook_kwargs = {
            'url': webhook_url,
            'allowed_updates': allowed_updates,
            'drop_pending_updates': True,
        }
        if settings.TELEGRAM_WEBHOOK_SECRET:
            webhook_kwargs['secret_token'] = settings.TELEGRAM_WEBHOOK_SECRET

        result = await bot.set_webhook(**webhook_kwargs)

        if result:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Webhook registered successfully!\n'
                f'   URL: {webhook_url}\n'
                f'   Updates: {allowed_updates}'
            ))
        else:
            self.stdout.write(self.style.ERROR('❌ Failed to register webhook'))

        info = await bot.get_webhook_info()
        self.stdout.write('\nWebhook info:')
        self.stdout.write(f'  URL: {info.url}')
        self.stdout.write(f'  Pending updates: {info.pending_update_count}')
        self.stdout.write(f'  Last error: {info.last_error_message or "none"}')
