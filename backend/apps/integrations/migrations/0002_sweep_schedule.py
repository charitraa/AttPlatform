from django.db import migrations


def forwards(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every_5, _ = IntervalSchedule.objects.get_or_create(every=5, period="minutes")
    PeriodicTask.objects.update_or_create(
        name="integrations: webhook retry sweep",
        defaults={"task": "integrations.sweep_webhooks", "interval": every_5, "queue": "webhooks"},
    )


def backwards(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name="integrations: webhook retry sweep").delete()


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial"), ("django_celery_beat", "0019_alter_periodictasks_options")]
    operations = [migrations.RunPython(forwards, backwards)]
