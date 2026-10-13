import django.contrib.postgres.indexes
import django.db.models.deletion
from django.db import migrations, models


def add_topic_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS question_active_tags_gin ON quiz_question USING GIN (topic_tags jsonb_path_ops) WHERE is_active')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT indisvalid FROM pg_index JOIN pg_class ON pg_class.oid = pg_index.indexrelid WHERE pg_class.relname = %s", ['question_active_tags_gin'])
        row = cursor.fetchone()
    if not row or not row[0]:
        raise RuntimeError('Topic index is invalid; review/drop the incomplete index before retrying migration.')


def remove_topic_index(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP INDEX CONCURRENTLY IF EXISTS question_active_tags_gin')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ('accounts', '0008_subscriptionrequest_payment_reference'),
        ('content', '0016_alter_fileinbox_file_alter_resource_file'),
        ('quiz', '0010_backfill_attempt_denominators'),
    ]
    operations = [
        # Add the covering index before removing its redundant single-column FK index.
        migrations.AddIndex(model_name='quizattempt', index=models.Index(fields=['student', '-completed_at', '-id'], name='attempt_student_recent_idx')),
        migrations.AlterField(model_name='quizattempt', name='student', field=models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, related_name='quiz_attempts', to='accounts.student')),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_topic_index, remove_topic_index, atomic=False)],
            state_operations=[migrations.AddIndex(model_name='question', index=django.contrib.postgres.indexes.GinIndex(condition=models.Q(is_active=True), fields=['topic_tags'], name='question_active_tags_gin', opclasses=['jsonb_path_ops']))],
        ),
    ]
