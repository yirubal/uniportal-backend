import logging
from django.utils import timezone
from asgiref.sync import sync_to_async
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from apps.content.models import FileInbox
from .downloader import download_file, get_file_info

logger = logging.getLogger(__name__)


# ─── Channel File Harvesting ──────────────────────────────────────────────────

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles every new post in the university channel.
    Downloads files and saves them to FileInbox for admin review.
    """
    message = update.channel_post
    if not message:
        return

    file_id, filename = get_file_info(message)
    if not file_id:
        logger.info(f'Skipping text-only message {message.message_id}')
        return

    already_exists = await sync_to_async(
        FileInbox.objects.filter(telegram_message_id=message.message_id).exists
    )()
    if already_exists:
        logger.info(f'Already downloaded message {message.message_id}, skipping')
        return

    logger.info(f'New file detected in channel: {filename}')

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

    from .tasks import process_inbox_item
    await process_inbox_item(inbox_item.id)


# ─── Student Commands ─────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — Welcome message with Mini App button.
    """
    from django.conf import settings

    user = update.effective_user
    mini_app_url = getattr(settings, 'MINI_APP_URL', '')

    if mini_app_url:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text='📚 Open Student Portal',
                web_app=WebAppInfo(url=mini_app_url),
            )],
            [InlineKeyboardButton(
                text='❓ Help',
                callback_data='show_help',
            )],
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text='❓ Help',
                callback_data='show_help',
            )],
        ])

    await update.message.reply_text(
        f'👋 Welcome, {user.first_name}!\n\n'
        f'🎓 *Unity University Student Portal*\n\n'
        f'Your one-stop platform for:\n'
        f'📖 Study materials — lecture notes, modules, worksheets\n'
        f'✅ Practice quizzes — course exams and exit exam prep\n'
        f'🏆 Exit exam simulation — timed, real exam experience\n\n'
        f'Tap the button below to open the portal 👇',
        parse_mode='Markdown',
        reply_markup=keyboard,
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help — Show available commands and how the portal works.
    """
    from django.conf import settings
    mini_app_url = getattr(settings, 'MINI_APP_URL', '')

    help_text = (
        '📚 *UniPortal Help*\n\n'
        '*Available Commands:*\n'
        '/start — Open the student portal\n'
        '/help — Show this help message\n'
        '/status — Check your subscription status\n\n'
        '*How it works:*\n'
        '1. Open the portal using /start\n'
        '2. Complete onboarding — pick your department, program, year and semester\n'
        '3. Browse study materials for your courses\n'
        '4. Practice quizzes and exit exam questions\n\n'
        '*Subscription:*\n'
        '🆓 Free — limited access to materials and questions\n'
        '⭐ Premium — full access to all materials, exit exams and simulations\n\n'
        '*To upgrade:*\n'
        'Open the portal → Subscription → Choose a plan → Follow payment instructions\n\n'
        '*Support:*\n'
        'If you have any issues contact your university admin.'
    )

    buttons = []
    if mini_app_url:
        buttons.append([InlineKeyboardButton(
            text='📚 Open Portal',
            web_app=WebAppInfo(url=mini_app_url),
        )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=keyboard,
    )


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status — Show the student's current subscription status.
    """
    from django.conf import settings
    from apps.accounts.models import Student

    user = update.effective_user

    try:
        student = await sync_to_async(Student.objects.get)(
            telegram_id=user.id
        )

        if student.is_premium:
            expiry = student.subscription_expiry.strftime('%B %d, %Y')
            status_text = (
                f'✅ *Premium Active*\n\n'
                f'📅 Expires: {expiry}\n'
                f'⏳ Days remaining: {student.days_remaining}\n\n'
                f'You have full access to all study materials and exit exam questions.'
            )
        else:
            status_text = (
                f'🆓 *Free Plan*\n\n'
                f'You currently have limited access.\n\n'
                f'Upgrade to Premium to unlock:\n'
                f'• All study materials\n'
                f'• Full exit exam question bank\n'
                f'• Timed exam simulations\n\n'
                f'Open the portal to upgrade 👇'
            )

        mini_app_url = getattr(settings, 'MINI_APP_URL', '')
        buttons = []
        if mini_app_url and not student.is_premium:
            buttons.append([InlineKeyboardButton(
                text='⭐ Upgrade to Premium',
                web_app=WebAppInfo(url=mini_app_url),
            )])
        elif mini_app_url:
            buttons.append([InlineKeyboardButton(
                text='📚 Open Portal',
                web_app=WebAppInfo(url=mini_app_url),
            )])

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        await update.message.reply_text(
            status_text,
            parse_mode='Markdown',
            reply_markup=keyboard,
        )

    except Student.DoesNotExist:
        await update.message.reply_text(
            '👋 Looks like you haven\'t opened the portal yet.\n\n'
            'Use /start to get started!',
        )


async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles any message that is not a recognized command.
    Gently guides the student to use the portal.
    """
    from django.conf import settings
    mini_app_url = getattr(settings, 'MINI_APP_URL', '')

    buttons = []
    if mini_app_url:
        buttons.append([InlineKeyboardButton(
            text='📚 Open Student Portal',
            web_app=WebAppInfo(url=mini_app_url),
        )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    await update.message.reply_text(
        '👋 Hi! I\'m the UniPortal bot.\n\n'
        'I don\'t process text messages — use the portal to access your study materials.\n\n'
        '*Available commands:*\n'
        '/start — Open the portal\n'
        '/help — Show help\n'
        '/status — Check subscription',
        parse_mode='Markdown',
        reply_markup=keyboard,
    )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles inline button callbacks.
    """
    query = update.callback_query
    await query.answer()

    if query.data == 'show_help':
        from django.conf import settings
        mini_app_url = getattr(settings, 'MINI_APP_URL', '')

        help_text = (
            '📚 *UniPortal Help*\n\n'
            '*Commands:*\n'
            '/start — Open the student portal\n'
            '/help — Show this message\n'
            '/status — Check your subscription\n\n'
            '*Support:*\n'
            'Contact your university admin for help.'
        )

        buttons = []
        if mini_app_url:
            buttons.append([InlineKeyboardButton(
                text='📚 Open Portal',
                web_app=WebAppInfo(url=mini_app_url),
            )])

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        await query.edit_message_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=keyboard,
        )