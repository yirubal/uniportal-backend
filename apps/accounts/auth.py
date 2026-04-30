import hashlib
import hmac
import time
from urllib.parse import unquote
from django.conf import settings


def validate_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise ValueError('initData is empty')

    parsed = {}
    for part in init_data.split('&'):
        if '=' in part:
            key, value = part.split('=', 1)
            parsed[key] = unquote(value)

    received_hash = parsed.pop('hash', None)
    if not received_hash:
        raise ValueError('Hash missing from initData')

    auth_date = parsed.get('auth_date')
    if auth_date:
        age = time.time() - int(auth_date)
        if age > 86400:
            raise ValueError('initData has expired')

    data_check_string = '\n'.join(
        f'{k}={v}'
        for k, v in sorted(parsed.items())
    )

    # ── Correct order: key first, then message ────────────────────────────────
    secret_key = hmac.new(
        key=settings.TELEGRAM_BOT_TOKEN.encode(),
        msg=b'WebAppData',
        digestmod=hashlib.sha256,
    ).digest()

    expected_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError('Invalid initData signature')

    import json
    user_str = parsed.get('user', '{}')
    try:
        user_data = json.loads(user_str)
    except json.JSONDecodeError:
        raise ValueError('Invalid user data in initData')

    return user_data