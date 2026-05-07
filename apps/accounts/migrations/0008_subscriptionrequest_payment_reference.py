from django.db import migrations, models


def copy_paid_from_to_payment_reference(apps, schema_editor):
    SubscriptionRequest = apps.get_model('accounts', 'SubscriptionRequest')
    for sub_request in SubscriptionRequest.objects.exclude(paid_from='').iterator():
        sub_request.payment_reference = sub_request.paid_from
        sub_request.save(update_fields=['payment_reference'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_broadcast_message'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionrequest',
            name='payment_reference',
            field=models.CharField(
                blank=True,
                help_text='Telebirr transaction number or CBE transaction ID provided by the student.',
                max_length=50,
            ),
        ),
        migrations.RunPython(
            copy_paid_from_to_payment_reference,
            migrations.RunPython.noop,
        ),
    ]
