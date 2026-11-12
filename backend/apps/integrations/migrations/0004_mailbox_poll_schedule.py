from django.db import migrations


def forwards(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every_2, _ = IntervalSchedule.objects.get_or_create(every=2, period="minutes")
    PeriodicTask.objects.update_or_create(
        name="integrations: poll mailboxes",
        defaults={"task": "integrations.poll_mailboxes", "interval": every_2, "queue": "webhooks"},
    )


def backwards(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name="integrations: poll mailboxes").delete()


class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_alter_integration_kind"), ("django_celery_beat", "0019_alter_periodictasks_options")]
    operations = [migrations.RunPython(forwards, backwards)]
