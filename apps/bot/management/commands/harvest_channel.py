"""
apps/bot/management/commands/harvest_channel.py

Backfills all historical files from the Telegram channel into FileInbox.

How it works:
    Telegram bots cannot read channel history directly or forward messages
    back to the same channel. Instead this script forwards each message to
    a private chat (the admin's Telegram chat with the bot) as a proxy,
    reads the file info from the forwarded copy, downloads it, then
    deletes the forwarded copy immediately.

Setup:
    1. Start a private chat with your bot on Telegram
    2. Send /start to the bot
    3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id
    4. Add TELEGRAM_ADMIN_CHAT_ID=your_chat_id to your .env file

Usage:
    python manage.py harvest_channel --admin-chat-id 123456789
    python manage.py harvest_channel --admin-chat-id 123456789 --dry-run
    python manage.py harvest_channel --admin-chat-id 123456789 --from-id 100
    python manage.py harvest_channel --admin-chat-id 123456789 --limit 50
"""

import asyncio
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MISS_THRESHOLD = 50


class Command(BaseCommand):
    help = 'Harvests all historical files from the Telegram channel into FileInbox.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--admin-chat-id',
            type=int,
            default=None,
            help='Your personal Telegram chat ID with the bot (used as proxy).',
        )
        parser.add_argument(
            '--from-id',
            type=int,
            default=1,
            help='Start scanning from this message ID (default: 1).',
        )
        parser.add_argument(
            '--to-id',
            type=int,
            default=None,
            help='Stop scanning at this message ID (default: auto-detect).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of files to download.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be downloaded without saving.',
        )
        parser.add_argument(
            '--redownload-missing',
            action='store_true',
            help='Re-download existing FileInbox rows when the stored file is missing.',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.5,
            help='Delay in seconds between requests (default: 0.5).',
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.ERROR('TELEGRAM_BOT_TOKEN is not set.'))
            return

        if not settings.TELEGRAM_CHANNEL_ID:
            self.stdout.write(self.style.ERROR('TELEGRAM_CHANNEL_ID is not set.'))
            return

        admin_chat_id = options['admin_chat_id'] or getattr(
            settings, 'TELEGRAM_ADMIN_CHAT_ID', None
        )

        if not admin_chat_id:
            self.stdout.write(self.style.ERROR(
                'Admin chat ID is required.\n'
                'Run: python manage.py harvest_channel --admin-chat-id YOUR_CHAT_ID\n\n'
                'To find your chat ID:\n'
                '1. Start a chat with your bot on Telegram\n'
                '2. Send any message to the bot\n'
                f'3. Visit: https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates\n'
                '4. Find the "id" field inside "chat" in the response'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Starting harvest from channel {settings.TELEGRAM_CHANNEL_ID}...\n'
            f'Using admin chat {admin_chat_id} as proxy.'
        ))

        asyncio.run(self._harvest(options, admin_chat_id))

    async def _harvest(self, options, admin_chat_id: int):
        import telegram

        bot        = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)
        channel    = settings.TELEGRAM_CHANNEL_ID
        from_id    = options['from_id']
        to_id      = options['to_id']
        limit      = options['limit']
        dry_run    = options['dry_run']
        redownload_missing = options['redownload_missing']
        delay      = options['delay']

        downloaded         = 0
        skipped            = 0
        failed             = 0
        consecutive_misses = 0
        current_id         = from_id

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] No files will be saved.\n'))

        while True:
            # ── Stop conditions ───────────────────────────────────────────────
            if to_id and current_id > to_id:
                self.stdout.write(f'Reached --to-id {to_id}, stopping.')
                break

            if limit and downloaded >= limit:
                self.stdout.write(f'Reached --limit {limit}, stopping.')
                break

            if consecutive_misses >= MISS_THRESHOLD:
                self.stdout.write(
                    f'Hit {MISS_THRESHOLD} consecutive missing messages — '
                    f'reached end of channel history.'
                )
                break

            # ── Forward message to proxy chat ─────────────────────────────────
            forwarded = None
            try:
                forwarded = await bot.forward_message(
                    chat_id=admin_chat_id,
                    from_chat_id=channel,
                    message_id=current_id,
                )
                consecutive_misses = 0

            except telegram.error.BadRequest as e:
                err = str(e).lower()
                if any(x in err for x in [
                    'message to forward not found',
                    'invalid message id',
                    'message_id_invalid',
                    'not found',
                ]):
                    consecutive_misses += 1
                    current_id += 1
                    continue
                else:
                    self.stdout.write(self.style.WARNING(f'[{current_id}] BadRequest: {e}'))
                    consecutive_misses += 1
                    current_id += 1
                    await asyncio.sleep(delay)
                    continue

            except telegram.error.RetryAfter as e:
                self.stdout.write(self.style.WARNING(
                    f'Rate limited — waiting {e.retry_after}s...'
                ))
                await asyncio.sleep(e.retry_after)
                continue

            except telegram.error.Forbidden:
                self.stdout.write(self.style.ERROR(
                    'Bot is not an admin of the channel or was blocked.'
                ))
                break

            except Exception as e:
                self.stdout.write(self.style.WARNING(f'[{current_id}] Unexpected error: {e}'))
                consecutive_misses += 1
                current_id += 1
                await asyncio.sleep(delay)
                continue

            # ── Check if message has a file ───────────────────────────────────
            from apps.bot.downloader import get_file_info
            file_id, filename = get_file_info(forwarded)

            # Delete proxy copy immediately
            try:
                await bot.delete_message(
                    chat_id=admin_chat_id,
                    message_id=forwarded.message_id,
                )
            except Exception:
                pass

            if not file_id:
                current_id += 1
                await asyncio.sleep(delay)
                continue

            # ── Check if already in FileInbox ─────────────────────────────────
            from asgiref.sync import sync_to_async
            from apps.content.models import FileInbox

            existing_item = await sync_to_async(
                lambda: FileInbox.objects.filter(telegram_message_id=current_id).first()
            )()

            if existing_item and not redownload_missing:
                self.stdout.write(f'  [{current_id}] Already exists — skipping {filename}')
                skipped += 1
                current_id += 1
                await asyncio.sleep(delay)
                continue

            if existing_item and redownload_missing:
                existing_file_exists = await sync_to_async(
                    lambda: bool(existing_item.file and existing_item.file.storage.exists(existing_item.file.name))
                )()
                if existing_file_exists:
                    self.stdout.write(f'  [{current_id}] Existing file is present — skipping {filename}')
                    skipped += 1
                    current_id += 1
                    await asyncio.sleep(delay)
                    continue
                self.stdout.write(self.style.WARNING(
                    f'  [{current_id}] Existing DB row has missing file — re-downloading {filename}'
                ))

            if dry_run:
                self.stdout.write(self.style.SUCCESS(f'  [{current_id}] Would download: {filename}'))
                downloaded += 1
                current_id += 1
                await asyncio.sleep(delay)
                continue

            # ── Download ──────────────────────────────────────────────────────
            self.stdout.write(f'  [{current_id}] Downloading: {filename}...')

            from apps.bot.downloader import download_file
            file_path = await download_file(bot, file_id, filename)

            if not file_path:
                self.stdout.write(self.style.WARNING(f'  [{current_id}] Failed to download {filename}'))
                await sync_to_async(FileInbox.objects.create)(
                    file='',
                    original_filename=filename,
                    telegram_message_id=current_id,
                    telegram_caption=forwarded.caption or '',
                    posted_date=forwarded.date or timezone.now(),
                    processing_status=FileInbox.STATUS_FAILED,
                    processing_error='Failed to download during harvest',
                )
                failed += 1
                current_id += 1
                await asyncio.sleep(delay)
                continue

            # ── Save to FileInbox ─────────────────────────────────────────────
            from apps.content.services import (
                create_inbox_item_from_local_file,
                save_local_file_to_inbox_item,
            )
            if existing_item:
                inbox_item = await sync_to_async(save_local_file_to_inbox_item)(
                    existing_item,
                    file_path=file_path,
                    original_filename=filename,
                    telegram_caption=forwarded.caption or '',
                    posted_date=forwarded.date or timezone.now(),
                    processing_status=FileInbox.STATUS_UNPROCESSED,
                    processing_error='',
                )
            else:
                inbox_item = await sync_to_async(create_inbox_item_from_local_file)(
                    file_path=file_path,
                    original_filename=filename,
                    telegram_message_id=current_id,
                    telegram_caption=forwarded.caption or '',
                    posted_date=forwarded.date or timezone.now(),
                    processing_status=FileInbox.STATUS_UNPROCESSED,  # ← fixed (was STATUS_FAILED)
                )

            from apps.bot.tasks import process_inbox_item
            await process_inbox_item(inbox_item.id)

            self.stdout.write(self.style.SUCCESS(f'  [{current_id}] ✅ Saved: {filename}'))
            downloaded += 1
            current_id += 1
            await asyncio.sleep(delay)

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('\n' + '─' * 50)
        self.stdout.write(self.style.SUCCESS(
            f'Harvest complete.\n'
            f'  Downloaded : {downloaded}\n'
            f'  Skipped    : {skipped} (already existed)\n'
            f'  Failed     : {failed}\n'
            f'  Last ID    : {current_id - 1}'
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\n[DRY RUN] No files were saved. Remove --dry-run to run for real.'
            ))
