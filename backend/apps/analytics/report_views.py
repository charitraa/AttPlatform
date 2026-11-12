"""Analytics report endpoints (JSON for the app, CSV for download)."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.organizations.permissions import HasPermission

from . import reports


def _window(request) -> reports.Window:
    tz = ZoneInfo(request.organization.timezone or "UTC")
    today = timezone.now().astimezone(tz).date()

    def day(name, default):
        raw = request.query_params.get(name)
        if not raw:
            return default
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise exceptions.ValidationError({name: ["Use YYYY-MM-DD."]}) from exc

    end = day("end", today)
    start = day("start", end - timedelta(days=29))
    if end < start:
        raise exceptions.ValidationError({"end": ["The end date is before the start date."]})
    if (end - start).days + 1 > reports.MAX_DAYS:
        raise exceptions.ValidationError({"end": [f"Reports cover at most {reports.MAX_DAYS} days."]})
    return reports.Window(start, end, tz)


@extend_schema(tags=["analytics"], responses=OpenApiTypes.OBJECT)
class ReportListView(APIView):
    """The available reports."""

    permission_classes = [HasPermission("analytics.view")]

    def get(self, request):
        return Response([{"name": n, "title": n.replace("_", " ").capitalize()} for n in reports.REPORTS])


class _ExportThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        return request.query_params.get("export") != "csv" or super().allow_request(request, view)


@extend_schema(
    tags=["analytics"],
    parameters=[
        OpenApiParameter("start", OpenApiTypes.DATE, description="Default: 29 days before end."),
        OpenApiParameter("end", OpenApiTypes.DATE, description="Default: today (organization time zone)."),
        OpenApiParameter("export", str, enum=["csv"], description="Download as CSV instead of JSON."),
    ],
    responses={(200, "application/json"): OpenApiTypes.OBJECT, (200, "text/csv"): OpenApiTypes.STR},
)
class ReportView(APIView):
    permission_classes = [HasPermission("analytics.view")]
    throttle_classes = [_ExportThrottle]
    throttle_scope = "export"

    def get(self, request, name):
        builder = reports.REPORTS.get(name)
        if builder is None:
            raise exceptions.NotFound("Unknown report.")
        report = builder(request.tenant, _window(request))
        if request.query_params.get("export") == "csv":
            audit.record(
                "analytics.exported",
                request=request,
                target_type="analytics.report",
                target_id=name,
                changes={"start": report.start.isoformat(), "end": report.end.isoformat(), "rows": len(report.rows)},
            )
            resp = HttpResponse(reports.to_csv(report), content_type="text/csv; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{name}_{report.start}_{report.end}.csv"'
            resp["Cache-Control"] = "no-store"
            return resp
        return Response(report.as_dict())
