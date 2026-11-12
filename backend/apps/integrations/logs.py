"""IntegrationLog writes and integration health. Summaries only: never secrets or full payloads."""

from django.utils import timezone

from .models import Integration, IntegrationLog


def record(
    integration: Integration,
    *,
    operation: str,
    ok: bool,
    direction=IntegrationLog.Direction.OUTBOUND,
    duration_ms=None,
    request="",
    response="",
    error="",
) -> IntegrationLog:
    now = timezone.now()
    if ok:
        Integration.objects.filter(pk=integration.pk).update(last_success_at=now)
        integration.last_success_at = now
    else:
        Integration.objects.filter(pk=integration.pk).update(last_error_at=now, last_error=str(error)[:500])
        integration.last_error_at, integration.last_error = now, str(error)[:500]
    return IntegrationLog.objects.create(
        integration=integration,
        direction=direction,
        operation=operation,
        status=IntegrationLog.Status.OK if ok else IntegrationLog.Status.ERROR,
        duration_ms=duration_ms,
        request_summary=str(request)[:500],
        response_summary=str(response)[:500],
        error=str(error)[:500],
    )
