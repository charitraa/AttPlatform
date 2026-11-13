from django.db import migrations


def forwards(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every_minute, _ = IntervalSchedule.objects.get_or_create(every=1, period="minutes")
    PeriodicTask.objects.update_or_create(
        name="notifications: link Telegram chats",
        defaults={"task": "notifications.poll_telegram", "interval": every_minute, "queue": "notifications"},
    )


def backwards(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name="notifications: link Telegram chats").delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_alter_notificationdelivery_channel_and_more"), ("django_celery_beat", "0019_alter_periodictasks_options")]
    operations = [migrations.RunPython(forwards, backwards)]
