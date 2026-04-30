import hashlib
import hmac
import json
import logging
import time
from urllib.parse import unquote

from django.conf import settings

logger = logging.getLogger(__name__)


def validate_telegram_init_data(init_data: str) -> dict:
    """
    Validates Telegram WebApp initData using HMAC-SHA256.
    Returns parsed user dict if valid.
    Raises ValueError if invalid or expired.
    """
    if not init_data:
        raise ValueError('initData is empty')

    # Parse the init_data string into key-value pairs
    parsed = {}
    for part in init_data.split('&'):
        if '=' in part:
            key, value = part.split('=', 1)
            parsed[key] = unquote(value)

    # Extract hash — must not be included in data check string
    received_hash = parsed.pop('hash', None)
    if not received_hash:
        raise ValueError('Hash missing from initData')

    # Remove fields that must be excluded from data check string
    parsed.pop('signature', None)
    parsed.pop('query_id', None)

    # Check timestamp — reject if older than 24 hours
    auth_date = parsed.get('auth_date')
    if auth_date:
        age = time.time() - int(auth_date)
        if age > 86400:
            raise ValueError('initData has expired')

    # Build data check string (sorted alphabetically, joined by newlines)
    data_check_string = '\n'.join(
        f'{k}={v}'
        for k, v in sorted(parsed.items())
    )

    # Generate secret key from bot token
    secret_key = hmac.new(
        key=b'WebAppData',
        msg=settings.TELEGRAM_BOT_TOKEN.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    # Calculate expected hash
    expected_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # TEMP DEBUG — remove after fixing
    logger.info(f'Token length: {len(settings.TELEGRAM_BOT_TOKEN)}')
    logger.info(f'Token first 10: {settings.TELEGRAM_BOT_TOKEN[:10]}')
    logger.info(f'Token last 5: {settings.TELEGRAM_BOT_TOKEN[-5:]}')
    logger.info(f'Data check string:\n{data_check_string}')
    logger.info(f'Expected: {expected_hash}')
    logger.info(f'Received: {received_hash}')
    logger.info(f'Match: {expected_hash == received_hash}')

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError('Invalid initData signature')

    # Parse user data
    user_str = parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    return user_data