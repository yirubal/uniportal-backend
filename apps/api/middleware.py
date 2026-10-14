import logging
import time
import traceback
from uuid import UUID, uuid4
from django.utils.functional import SimpleLazyObject
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from apps.accounts.models import Student

logger = logging.getLogger(__name__)


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request_id = str(UUID(request.headers.get('X-Request-ID', '')))
        except (ValueError, AttributeError):
            request_id = str(uuid4())
        request.request_id = request_id
        started = time.monotonic()
        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        match = request.resolver_match
        route = match.view_name if match else 'unresolved'
        # Paths/query strings can contain signed downloads; bodies include PII.
        log = logger.error if response.status_code >= 500 else logger.info
        if route not in ('health-check', 'liveness-check') or response.status_code >= 500:
            log('request_id=%s method=%s route=%s status=%s duration_ms=%.1f',
                request_id, request.method, route, response.status_code,
                (time.monotonic() - started) * 1000)
        return response

    def process_exception(self, request, exception):
        frames = traceback.extract_tb(exception.__traceback__)[-12:]
        locations = ' > '.join(f'{frame.filename}:{frame.lineno}:{frame.name}' for frame in frames)
        logger.error('request_id=%s error_type=%s frames=%s',
                     request.request_id, type(exception).__name__, locations)


def get_student_from_request(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None
    token_str = auth_header.split(' ')[1]
    try:
        token = AccessToken(token_str)
        student_id = token.get('student_id')
        if not student_id:
            return None
        return Student.objects.get(id=student_id, is_active=True)
    except (TokenError, Student.DoesNotExist):
        return None


class TelegramAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip middleware entirely for admin URLs
        if request.path.startswith('/admin/'):
            return self.get_response(request)

        request.student = SimpleLazyObject(
            lambda: get_student_from_request(request)
        )
        return self.get_response(request)
