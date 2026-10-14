import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl, unquote

from django.conf import settings

logger = logging.getLogger(__name__)


def _build_data_check_string(fields: dict[str, str]) -> str:
    return '\n'.join(
        f'{key}={value}'
        for key, value in sorted(fields.items())
    )


def _calculate_telegram_hash(data_check_string: str) -> str:
    # Telegram Mini App bot-token validation:
    # secret_key = HMAC_SHA256(bot_token, key="WebAppData")
    secret_key = hmac.new(
        key=b'WebAppData',
        msg=settings.TELEGRAM_BOT_TOKEN.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    return hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def validate_telegram_init_data(init_data: str) -> dict:
    """
    Validates Telegram WebApp initData using HMAC-SHA256.
    Returns parsed user dict if valid.
    Raises ValueError if invalid or expired.
    """
    if not isinstance(init_data, str) or not init_data:
        raise ValueError('initData is empty')

    # If the entire initData string was encoded once by mistake, recover it.
    # Normal Telegram initData contains '&' between fields.
    if '&' not in init_data and '%26' in init_data:
        init_data = unquote(init_data)

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    parsed = dict(pairs)
    if len(parsed) != len(pairs):
        raise ValueError('Duplicate initData fields')

    # Extract hash — must not be included in data check string
    received_hash = parsed.pop('hash', None)
    if not received_hash or len(received_hash) != 64 or any(c not in '0123456789abcdef' for c in received_hash):
        raise ValueError('A valid hash is required in initData')

    auth_date = parsed.get('auth_date', '')
    if not auth_date.isascii() or not auth_date.isdecimal() or len(auth_date) > 12 or int(auth_date) <= 0:
        raise ValueError('A valid auth_date is required')
    age = time.time() - int(auth_date)
    if age > 86400:
        raise ValueError('initData has expired')
    if age < -60:
        raise ValueError('initData timestamp is in the future')

    # Bot-token validation signs all received fields except hash. Telegram's
    # newer initData can also include "signature" for third-party validation;
    # accept both variants so clients from either Telegram format validate.
    candidate_fields = [parsed]
    if 'signature' in parsed:
        without_signature = parsed.copy()
        without_signature.pop('signature', None)
        candidate_fields.append(without_signature)

    is_valid = any(
        hmac.compare_digest(
            _calculate_telegram_hash(_build_data_check_string(fields)),
            received_hash,
        )
        for fields in candidate_fields
    )

    if not is_valid:
        logger.warning('Invalid Telegram initData signature')
        raise ValueError('Invalid initData signature')

    # Parse user data
    user_str = parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    if (not isinstance(user_data, dict) or isinstance(user_data.get('id'), bool)
            or not isinstance(user_data.get('id'), int)
            or not 0 < user_data['id'] <= 9223372036854775807):
        raise ValueError('Invalid Telegram user ID')
    for field in ('first_name', 'last_name', 'username'):
        if field in user_data and (not isinstance(user_data[field], str) or len(user_data[field]) > 255):
            raise ValueError('Invalid Telegram user data')
    return user_data
