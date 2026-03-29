import logging
from django.utils.functional import SimpleLazyObject
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from apps.accounts.models import Student

logger = logging.getLogger(__name__)


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
        request.student = SimpleLazyObject(
            lambda: get_student_from_request(request)
        )
        return self.get_response(request)