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
    if not init_data:
        raise ValueError('initData is empty')

    # If the entire initData string was encoded once by mistake, recover it.
    # Normal Telegram initData contains '&' between fields.
    if '&' not in init_data and '%26' in init_data:
        init_data = unquote(init_data)

    parsed = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))

    # Extract hash — must not be included in data check string
    received_hash = parsed.pop('hash', None)
    if not received_hash:
        raise ValueError('Hash missing from initData')

    # Check timestamp — reject if older than 24 hours
    auth_date = parsed.get('auth_date')
    if auth_date:
        age = time.time() - int(auth_date)
        if age > 86400:
            raise ValueError('initData has expired')

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
        logger.warning(
            'Invalid Telegram initData signature. Parsed keys: %s',
            sorted(parsed.keys()),
        )
        raise ValueError('Invalid initData signature')

    # Parse user data
    user_str = parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    return user_data
