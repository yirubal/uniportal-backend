import hashlib
import hmac
import time
from urllib.parse import unquote
from django.conf import settings


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

    # Extract hash from parsed data
    received_hash = parsed.pop('hash', None)
    if not received_hash:
        raise ValueError('Hash missing from initData')

    # Check timestamp — reject if older than 24 hours
    auth_date = parsed.get('auth_date')
    if auth_date:
        age = time.time() - int(auth_date)
        if age > 86400:  # 24 hours
            raise ValueError('initData has expired')

    # Build data check string (sorted alphabetically, joined by newlines)
    data_check_string = '\n'.join(
        f'{k}={v}'
        for k, v in sorted(parsed.items())
    )

    # Generate secret key from bot token
    secret_key = hmac.new(
        b'WebAppData',
        settings.TELEGRAM_BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    # Calculate expected hash
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError('Invalid initData signature')

    # Parse user data from the user field
    import json
    user_str = parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    return user_data