from celery import shared_task


@shared_task(name="field_service.purge_old_locations")
def purge_old_locations() -> int:
    """Location pings are kept for 30 days only (privacy)."""
    from .services import purge_old_locations as purge

    return purge()
