"""Exact topic matching and bounded question selection on the database."""
from django.db import connection
from django.db.models import BooleanField, Q
from django.db.models.expressions import RawSQL

from .models import Question

MAX_QUESTIONS = 500


def filter_topic_tags(queryset, topics):
    topics = list(dict.fromkeys(topics))
    if not topics:
        return queryset.none()
    if connection.features.supports_json_field_contains:
        condition = Q()
        for topic in topics:
            condition |= Q(topic_tags__contains=[topic])
        return queryset.filter(condition)
    # SQLite's JSON1 keeps local behavior consistent without loading the bank.
    table = connection.ops.quote_name(queryset.query.get_initial_alias())
    placeholders = ', '.join(['%s'] * len(topics))
    match = RawSQL(
        f"json_type({table}.topic_tags) = 'array' AND EXISTS (SELECT 1 FROM json_each({table}.topic_tags) tag WHERE tag.type = 'text' AND tag.value IN ({placeholders}))",
        topics, output_field=BooleanField(),
    )
    return queryset.alias(topic_match=match).filter(topic_match=True)


def select_random_questions(queryset, limit):
    # Randomize lightweight IDs across the entire eligible bank; fetch full
    # question/option/chapter data only for the bounded selected set.
    limit = max(1, min(limit or MAX_QUESTIONS, MAX_QUESTIONS))
    ids = list(queryset.order_by('?').values_list('pk', flat=True)[:limit])
    rows = {row.pk: row for row in Question.objects.filter(pk__in=ids).select_related('chapter')}
    return [rows[pk] for pk in ids if pk in rows]
