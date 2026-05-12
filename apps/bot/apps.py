from django.apps import AppConfig


class BotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.bot'

    def ready(self):
        """
        Build the bot Application once in web processes so the first webhook
        request does not pay handler-registration cost. Management commands skip
        this to avoid Telegram client setup during migrations/tests.
        """
        import logging
        import os
        import sys

        command = sys.argv[1] if len(sys.argv) > 1 else ''
        skip_commands = {
            'check',
            'collectstatic',
            'harvest_channel',
            'makemigrations',
            'migrate',
            'run_bot',
            'setup_webhook',
            'shell',
            'test',
        }

        if command in skip_commands:
            return

        if command == 'runserver' and os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from django.conf import settings

            if not settings.TELEGRAM_BOT_TOKEN:
                return

            from apps.bot.application import get_application

            get_application()
        except Exception as exc:
            logging.getLogger(__name__).warning('Bot init skipped: %s', exc)
