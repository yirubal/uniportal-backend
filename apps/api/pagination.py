"""Incremental pagination without changing legacy array response contracts."""
from django.conf import settings
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response


class ListPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def list_response(queryset, serializer_class, request, *, legacy_limit=None):
    if 'page' in request.query_params or 'page_size' in request.query_params:
        raw_size = request.query_params.get('page_size', '50')
        try:
            size = int(raw_size)
        except (ValueError, TypeError):
            raise ValidationError({'page_size': 'Use an integer from 1 to 200.'})
        if not 1 <= size <= 200:
            raise ValidationError({'page_size': 'Use an integer from 1 to 200.'})
        paginator = ListPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(serializer_class(page, many=True, context={'request': request}).data)
    limit = legacy_limit or settings.API_LEGACY_LIST_LIMIT
    rows = list(queryset[:limit + 1])
    if len(rows) > limit:
        # Do not silently truncate a catalogue for a client that hasn't migrated.
        raise ValidationError({'pagination': 'This list requires pagination. Use page=1&page_size=50.'})
    return Response(serializer_class(rows, many=True, context={'request': request}).data)
