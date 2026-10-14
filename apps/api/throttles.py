from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class StudentRateThrottle(UserRateThrottle):
    """General availability throttle, keyed by the authenticated student."""
    def get_cache_key(self, request, view):
        student = getattr(request, 'student', None)
        if not student:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': f'student:{student.pk}'}


class StudentAwareAnonThrottle(AnonRateThrottle):
    def get_cache_key(self, request, view):
        if getattr(request, 'student', None):
            return None
        return super().get_cache_key(request, view)


class AuthRateThrottle(AnonRateThrottle):
    scope = 'auth'
    cache = caches['throttles']


class SubscriptionRateThrottle(StudentRateThrottle):
    scope = 'subscription'
    cache = caches['throttles']
