from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.bot.application import BOT_COMMANDS, set_visible_bot_commands


class BotCommandRegistrationTests(TestCase):
    def test_exam_command_is_removed_from_telegram_menu(self):
        commands = {command.command: command.description for command in BOT_COMMANDS}

        self.assertNotIn('exam', commands)
        self.assertEqual(
            list(commands.keys()),
            ['start', 'help', 'status'],
        )
        self.assertEqual(commands['start'], 'Open UniPortal')
        self.assertEqual(commands['help'], 'How to use the portal')
        self.assertEqual(commands['status'], 'Check your subscription')

    def test_set_visible_bot_commands_sends_full_command_list(self):
        bot = SimpleNamespace(set_my_commands=AsyncMock())
        application = SimpleNamespace(bot=bot)

        async_to_sync(set_visible_bot_commands)(application)

        bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)


class TelegramWebhookViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_WEBHOOK_SECRET='secret')
    def test_rejects_invalid_secret_header(self):
        from .models import TelegramUpdate
        response = self.client.post('/api/telegram/webhook/', {'update_id': 123}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TelegramUpdate.objects.exists())

    @override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_WEBHOOK_SECRET='secret')
    def test_persists_and_deduplicates_without_processing_in_request(self):
        from .models import TelegramUpdate
        with patch('apps.bot.application.process_telegram_update') as process:
            for _ in range(2):
                response = self.client.post('/api/telegram/webhook/', {'update_id': 123}, format='json',
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='secret')
                self.assertEqual(response.status_code, 200)
        self.assertEqual(TelegramUpdate.objects.count(), 1)
        self.assertEqual(TelegramUpdate.objects.get().status, 'pending')
        process.assert_not_called()

    @override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_WEBHOOK_SECRET='')
    def test_returns_503_when_persistence_fails(self):
        with patch('apps.bot.models.TelegramUpdate.objects.get_or_create', side_effect=RuntimeError('Database down')):
            with self.assertLogs('apps.api.views', level='ERROR'):
                response = self.client.post('/api/telegram/webhook/', {'update_id': 123}, format='json')
        self.assertEqual(response.status_code, 503)

    @override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_WEBHOOK_SECRET='')
    def test_invalid_payloads_return_400(self):
        for data in ({}, {'update_id': 'abc'}, {'update_id': True}, {'update_id': -1}, {'update_id': 2**64}):
            response = self.client.post('/api/telegram/webhook/', data, format='json')
            self.assertEqual(response.status_code, 400)



class SetupWebhookCommandTests(TestCase):
    @override_settings(
        TELEGRAM_BOT_TOKEN='123:test-token',
        TELEGRAM_WEBHOOK_SECRET='webhook-secret',
        TELEGRAM_WEBHOOK_URL='https://example.test/api/telegram/webhook/',
    )
    def test_registers_webhook_with_secret_and_command_menu(self):
        with patch('telegram.Bot', _FakeTelegramBot):
            output = StringIO()
            call_command('setup_webhook', stdout=output)

        fake_bot = _FakeTelegramBot.instances[-1]
        self.assertEqual(fake_bot.token, '123:test-token')
        self.assertEqual(fake_bot.commands, BOT_COMMANDS)
        self.assertEqual(fake_bot.webhook_kwargs, {
            'url': 'https://example.test/api/telegram/webhook/',
            'allowed_updates': ['message', 'channel_post', 'callback_query'],
            'drop_pending_updates': True,
            'secret_token': 'webhook-secret',
        })
        self.assertIn('Webhook registered successfully', output.getvalue())

    @override_settings(TELEGRAM_BOT_TOKEN='123:test-token')
    def test_delete_removes_webhook(self):
        with patch('telegram.Bot', _FakeTelegramBot):
            call_command('setup_webhook', '--delete', stdout=StringIO())

        fake_bot = _FakeTelegramBot.instances[-1]
        self.assertEqual(fake_bot.delete_kwargs, {'drop_pending_updates': True})


class _FakeTelegramBot:
    instances = []

    def __init__(self, token=''):
        self.token = token
        self.commands = None
        self.webhook_kwargs = None
        self.delete_kwargs = None
        self.instances.append(self)

    async def set_my_commands(self, commands):
        self.commands = commands

    async def set_webhook(self, **kwargs):
        self.webhook_kwargs = kwargs
        return True

    async def get_webhook_info(self):
        return SimpleNamespace(
            url=self.webhook_kwargs['url'],
            pending_update_count=0,
            last_error_message=None,
        )

    async def delete_webhook(self, **kwargs):
        self.delete_kwargs = kwargs
        return True
