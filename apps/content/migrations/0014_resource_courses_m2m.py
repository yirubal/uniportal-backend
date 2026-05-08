import django.db.models.deletion
from django.db import migrations, models


def copy_course_to_courses(apps, schema_editor):
    Resource = apps.get_model('content', 'Resource')
    for resource in Resource.objects.all():
        if resource.course_id:
            resource.courses.add(resource.course_id)


def reverse_copy(apps, schema_editor):
    Resource = apps.get_model('content', 'Resource')
    for resource in Resource.objects.all():
        first_course = resource.courses.first()
        if first_course:
            resource.course_id = first_course.id
            resource.save(update_fields=['course'])


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0013_resource_source'),
    ]

    operations = [
        migrations.AlterField(
            model_name='resource',
            name='course',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='resources',
                to='content.course',
            ),
        ),
        migrations.AddField(
            model_name='resource',
            name='courses',
            field=models.ManyToManyField(
                blank=True,
                related_name='resources',
                to='content.course',
            ),
        ),
        migrations.RunPython(copy_course_to_courses, reverse_copy),
        migrations.RemoveIndex(
            model_name='resource',
            name='resource_course_status_acc_idx',
        ),
        migrations.RemoveField(
            model_name='resource',
            name='course',
        ),
    ]
