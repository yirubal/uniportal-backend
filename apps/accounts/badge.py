"""
apps/accounts/badge.py

Used by Unfold sidebar to show the count of pending subscription requests.
Referenced in settings.py UNFOLD config as 'apps.accounts.badge_pending_requests'
"""


def badge_pending_requests(request):
    from apps.accounts.models import SubscriptionRequest
    count = SubscriptionRequest.objects.filter(
        status=SubscriptionRequest.STATUS_PENDING
    ).count()
    return str(count) if count else None