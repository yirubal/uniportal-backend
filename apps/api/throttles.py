"""
apps/api/throttles.py

Custom throttle classes for specific endpoints.
"""
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """Throttle for login/auth endpoints — stricter limit."""
    scope = 'auth'


class SubscriptionRateThrottle(UserRateThrottle):
    """Throttle for subscription request endpoint."""
    scope = 'subscription'