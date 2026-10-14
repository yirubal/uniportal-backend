from django.db import models


class ThrottleCacheEntry(models.Model):
    """Django DatabaseCache table for shared auth/payment throttle histories."""
    cache_key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()
    expires = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'api_throttle_cache'
