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

    Important: data check string must be built from RAW (URL-encoded) values,
    not decoded values. Only the hash comparison uses decoded values.
    """
    if not init_data:
        raise ValueError('initData is empty')

    # Parse into both raw and decoded versions
    raw_parsed     = {}  # URL-encoded — used for data check string
    decoded_parsed = {}  # decoded — used for reading actual values

    for part in init_data.split('&'):
        if '=' in part:
            key, value = part.split('=', 1)
            raw_parsed[key]     = value
            decoded_parsed[key] = unquote(value)

    # Extract hash — exclude from data check string
    received_hash = decoded_parsed.pop('hash', None)
    raw_parsed.pop('hash', None)
    if not received_hash:
        raise ValueError('Hash missing from initData')

    # Remove fields that must be excluded from data check string
    for field in ('signature', 'query_id'):
        raw_parsed.pop(field, None)
        decoded_parsed.pop(field, None)

    # Check timestamp
    auth_date = decoded_parsed.get('auth_date')
    if auth_date:
        age = time.time() - int(auth_date)
        if age > 86400:
            raise ValueError('initData has expired')

    # Build data check string from RAW URL-encoded values (sorted alphabetically)
    data_check_string = '\n'.join(
        f'{k}={v}'
        for k, v in sorted(raw_parsed.items())
    )

    # Generate secret key
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
    logger.info(f'Data check string:\n{data_check_string[:300]}')
    logger.info(f'Expected: {expected_hash}')
    logger.info(f'Received: {received_hash}')
    logger.info(f'Match: {expected_hash == received_hash}')

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError('Invalid initData signature')

    # Parse user data from decoded value
    user_str = decoded_parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    return user_data