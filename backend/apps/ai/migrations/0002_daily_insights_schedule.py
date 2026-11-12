from django.db import migrations

TASK_NAME = "ai: daily insights"


def create_schedule(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="6", day_of_week="*", day_of_month="*", month_of_year="*", timezone="UTC"
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME, defaults={"task": "ai.generate_daily_insights", "crontab": crontab, "queue": "ai"}
    )


def remove_schedule(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]
    operations = [migrations.RunPython(create_schedule, remove_schedule)]
