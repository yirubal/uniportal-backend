import logging
from django.utils import timezone
from asgiref.sync import sync_to_async
from telegram import Update
from telegram.ext import ContextTypes

from apps.content.models import FileInbox
from .downloader import download_file, get_file_info

logger = logging.getLogger(__name__)


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles every new post in the university channel.
    Downloads files and saves them to FileInbox for admin review.
    """
    message = update.channel_post
    if not message:
        return

    # Skip text-only messages
    file_id, filename = get_file_info(message)
    if not file_id:
        logger.info(f'Skipping text-only message {message.message_id}')
        return

    # Skip if already downloaded
    already_exists = await sync_to_async(
        FileInbox.objects.filter(telegram_message_id=message.message_id).exists
    )()
    if already_exists:
        logger.info(f'Already downloaded message {message.message_id}, skipping')
        return

    logger.info(f'New file detected in channel: {filename}')

    # Download the file
    file_path = await download_file(context.bot, file_id, filename)

    if not file_path:
        logger.error(f'Failed to download {filename}')
        await sync_to_async(FileInbox.objects.create)(
            file='',
            original_filename=filename,
            telegram_message_id=message.message_id,
            telegram_caption=message.caption or '',
            posted_date=message.date or timezone.now(),
            processing_status=FileInbox.STATUS_FAILED,
            processing_error='Failed to download file from Telegram',
        )
        return

    # Save to FileInbox
    from django.conf import settings
    relative_path = file_path.replace(
        str(settings.MEDIA_ROOT), ''
    ).lstrip('/')

    inbox_item = await sync_to_async(FileInbox.objects.create)(
        file=relative_path,
        original_filename=filename,
        telegram_message_id=message.message_id,
        telegram_caption=message.caption or '',
        posted_date=message.date or timezone.now(),
        processing_status=FileInbox.STATUS_UNPROCESSED,
    )

    logger.info(f'Saved to FileInbox: {inbox_item.id} — {filename}')

    # Trigger text extraction
    from .tasks import process_inbox_item
    await process_inbox_item(inbox_item.id)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles /start command from students.
    Sends welcome message with Mini App button.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from django.conf import settings

    user = update.effective_user
    mini_app_url = getattr(settings, 'MINI_APP_URL', 'https://example.com')

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text='📚 Open Student Portal',
            web_app=WebAppInfo(url=mini_app_url)
        )]
    ])

    await update.message.reply_text(
        f'Welcome {user.first_name}! 🎓\n\n'
        f'Access your Unity University study materials, '
        f'practice quizzes, and exit exam preparation.\n\n'
        f'Tap the button below to open the portal.',
        reply_markup=keyboard,
    )