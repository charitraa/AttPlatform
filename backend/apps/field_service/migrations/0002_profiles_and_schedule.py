from django.db import migrations


def forwards(apps, schema_editor):
    Membership = apps.get_model("organizations", "Membership")
    Technician = apps.get_model("field_service", "Technician")
    for m in Membership.objects.filter(is_active=True, role__code="field_technician"):
        Technician.objects.get_or_create(organization_id=m.organization_id, user_id=m.user_id)

    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="3", day_of_week="*", day_of_month="*", month_of_year="*", timezone="UTC"
    )
    PeriodicTask.objects.update_or_create(
        name="field service: purge old locations",
        defaults={"task": "field_service.purge_old_locations", "crontab": crontab},
    )


def backwards(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(
        name="field service: purge old locations"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("field_service", "0001_initial"),
        ("organizations", "0002_organizationsequence"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
