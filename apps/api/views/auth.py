"""Auth API endpoints."""
import logging
import hmac
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings
from ..throttles import AuthRateThrottle
from apps.accounts.models import Student
from apps.accounts.auth import validate_telegram_init_data
from ..serializers import StudentSerializer

logger = logging.getLogger(__name__)


class TelegramAuthView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({'error': 'A JSON object is required.'}, status=400)
        init_data = request.data.get('init_data', '')

        if settings.DEBUG and request.data.get('dev_mode'):
            student, _ = Student.objects.get_or_create(
                telegram_id=request.data.get('telegram_id', 999999),
                defaults={
                    'first_name': request.data.get('first_name', 'Dev'),
                    'username': request.data.get('username', 'devuser'),
                }
            )
            token = _generate_jwt(student)
            return Response({
                'token': token,
                'student': StudentSerializer(student).data,
            })

        try:
            user_data = validate_telegram_init_data(init_data)
        except ValueError as e:
            return Response(
                {'error': 'AUTH_FAILED', 'message': str(e)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ── Channel membership gate ───────────────────────────────────────────
        # This runs for BOTH /start and the "Open App" menu button (which opens
        # the mini app directly, bypassing all bot handlers).
        channel_id = getattr(settings, 'TELEGRAM_OFFICIAL_CHANNEL_ID', '')
        if channel_id:
            from apps.accounts.notifications import check_channel_membership_sync
            if not check_channel_membership_sync(user_data['id']):
                return Response(
                    {
                        'error':       'CHANNEL_REQUIRED',
                        'message':     'You must join our official channel before using the app.',
                        'channel_url': getattr(
                            settings,
                            'TELEGRAM_CHANNEL_LINK',
                            'https://t.me/unityuniversityportal',
                        ),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        student, created = Student.objects.update_or_create(
            telegram_id=user_data['id'],
            defaults={
                'first_name': user_data.get('first_name', ''),
                'last_name':  user_data.get('last_name', ''),
                'username':   user_data.get('username', ''),
            }
        )

        token = _generate_jwt(student)
        return Response({
            'token': token,
            'student': StudentSerializer(student).data,
        })


class TelegramWebhookView(APIView):
    """
    Receives Telegram updates via webhook POST requests.
    Telegram authenticates with the secret-token header configured on webhook setup.
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        secret = settings.TELEGRAM_WEBHOOK_SECRET
        if secret:
            token_header = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
            if not hmac.compare_digest(token_header.encode(), secret.encode()):
                logger.warning('Webhook request with invalid secret token')
                return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        if not settings.TELEGRAM_BOT_TOKEN:
            return Response({'error': 'Bot not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        from apps.bot.models import TelegramUpdate
        payload = request.data
        if (not isinstance(payload, dict) or isinstance(payload.get('update_id'), bool)
                or not isinstance(payload.get('update_id'), int)
                or not 0 <= payload['update_id'] <= 9223372036854775807):
            return Response({'error': 'A valid update_id is required.'}, status=400)
        channel_post = payload.get('channel_post') or payload.get('edited_channel_post')
        if channel_post:
            source = str(settings.TELEGRAM_CHANNEL_ID).strip()
            chat = channel_post.get('chat', {}) if isinstance(channel_post, dict) else {}
            if not isinstance(chat, dict) or not source or str(chat.get('id', '')) != source:
                return Response({'ok': True})
        try:
            TelegramUpdate.objects.get_or_create(update_id=payload['update_id'], defaults={'payload': payload})
        except Exception as exc:
            logger.error('Webhook persistence failed (%s)', type(exc).__name__)
            return Response({'error': 'Temporarily unable to accept update.'}, status=503)
        return Response({'ok': True})


def _generate_jwt(student: Student) -> str:
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken()
    refresh['student_id']  = student.id
    refresh['telegram_id'] = student.telegram_id
    return str(refresh.access_token)
