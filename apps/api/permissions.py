from rest_framework.permissions import BasePermission
from django.utils import timezone

FREE_QUIZ_LIMIT = 5


class IsTelegramAuthenticated(BasePermission):
    """
    Checks that request.student exists and is active.
    """
    message = 'Authentication required.'

    def has_permission(self, request, view):
        return (
            hasattr(request, 'student') and
            request.student is not None and
            request.student.is_active
        )


class IsPremium(BasePermission):
    """
    Allows access only to premium students with valid subscription.
    """
    message = {
        'error': 'INSUFFICIENT_ACCESS',
        'message': 'Upgrade to premium to access this feature.',
        'upgrade_required': True,
    }

    def has_permission(self, request, view):
        if not hasattr(request, 'student'):
            return False
        return request.student.is_premium


class FreeQuotaNotExceeded(BasePermission):
    """
    For free users — checks daily quiz question quota.
    Premium users always pass.
    """
    message = {
        'error': 'QUOTA_EXCEEDED',
        'message': f'You have used your {FREE_QUIZ_LIMIT} free questions for today. Upgrade to continue.',
        'upgrade_required': True,
    }

    def has_permission(self, request, view):
        if not hasattr(request, 'student'):
            return False
        student = request.student
        if student.is_premium:
            return True
        student.reset_daily_quota()
        return student.downloads_today < FREE_QUIZ_LIMIT