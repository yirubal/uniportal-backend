from django.db import migrations


def backfill_attempt_denominators(apps, schema_editor):
    Attempt = apps.get_model('quiz', 'QuizAttempt')
    alias = schema_editor.connection.alias
    updates = []
    attempts = Attempt.objects.using(alias).filter(gradable_total__isnull=True).only(
        'pk', 'score', 'total_questions', 'detailed_answers',
    )
    types = {'mcq', 'true_false', 'fill_blank', 'matching', 'essay'}
    for attempt in attempts.iterator(chunk_size=500):
        details = attempt.detailed_answers
        if not isinstance(details, dict) or not details or len(details) != attempt.total_questions:
            continue
        if any(not isinstance(row, dict) or not ('is_pending' in row or row.get('question_type') in types)
               for row in details.values()):
            continue
        pending = sum(bool(row.get('is_pending')) or row.get('question_type') in {'essay', 'matching'}
                      for row in details.values())
        gradable = attempt.total_questions - pending
        if attempt.score > gradable:
            continue
        attempt.gradable_total = gradable
        attempt.pending_count = pending
        updates.append(attempt)
        if len(updates) == 500:
            Attempt.objects.using(alias).bulk_update(updates, ['gradable_total', 'pending_count'])
            updates = []
    if updates:
        Attempt.objects.using(alias).bulk_update(updates, ['gradable_total', 'pending_count'])


class Migration(migrations.Migration):
    dependencies = [('quiz', '0009_quizattempt_gradable_total_quizattempt_pending_count_and_more')]
    operations = [migrations.RunPython(backfill_attempt_denominators, migrations.RunPython.noop)]
