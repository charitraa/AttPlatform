from django.db import migrations

# Mirrors services.DEFAULT_TARGETS / DEFAULT_SCHEDULE (migrations must not import live code).
TARGETS = {"critical": (30, 240), "high": (60, 480), "medium": (240, 1440), "low": (480, 2400)}
SCHEDULE = {d: [["09:00", "17:00"]] for d in ("sun", "mon", "tue", "wed", "thu", "fri")}


def forwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    BusinessHours = apps.get_model("sla", "BusinessHours")
    SLAPolicy = apps.get_model("sla", "SLAPolicy")
    SLATarget = apps.get_model("sla", "SLATarget")
    for org in Organization.objects.all():
        if SLAPolicy.objects.filter(organization=org, is_default=True).exists():
            continue
        hours, _ = BusinessHours.objects.get_or_create(
            organization=org, name="Standard hours", defaults={"timezone": org.timezone or "UTC", "schedule": SCHEDULE}
        )
        policy = SLAPolicy.objects.create(
            organization=org,
            name="Standard",
            description="Default targets for every ticket that no other policy matches.",
            is_default=True,
            business_hours=hours,
            priority_order=1000,
        )
        for priority, (response, resolution) in TARGETS.items():
            SLATarget.objects.create(
                policy=policy, priority=priority, first_response_minutes=response, resolution_minutes=resolution
            )

    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every_minute, _ = IntervalSchedule.objects.get_or_create(every=1, period="minutes")
    PeriodicTask.objects.update_or_create(
        name="sla: monitor", defaults={"task": "sla.scan", "interval": every_minute, "queue": "sla"}
    )


def backwards(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name="sla: monitor").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sla", "0001_initial"),
        ("organizations", "0002_organizationsequence"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
