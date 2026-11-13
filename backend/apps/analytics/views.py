from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import HasPermission

from . import dashboard

VIEW = ("tickets.view_all", "tickets.view_own")
DAYS = OpenApiParameter("days", int, description="Look-back window in days (7–180, default 30)")


def _days(request) -> int:
    try:
        return max(7, min(180, int(request.query_params.get("days", 30))))
    except ValueError as exc:
        raise serializers.ValidationError({"days": ["Must be a whole number."]}) from exc


class DashboardView(APIView):
    permission_classes = [HasPermission(*VIEW, any_of=True)]


@extend_schema(tags=["dashboard"], parameters=[DAYS], responses=OpenApiTypes.OBJECT)
class SummaryView(DashboardView):
    def get(self, request):
        return Response(dashboard.summary(request.tenant, days=_days(request)))


@extend_schema(tags=["dashboard"], parameters=[DAYS], responses=OpenApiTypes.OBJECT)
class TrendsView(DashboardView):
    def get(self, request):
        return Response({"days": dashboard.trends(request.tenant, days=_days(request))})


@extend_schema(tags=["dashboard"], responses=OpenApiTypes.OBJECT)
class BreakdownView(DashboardView):
    def get(self, request):
        return Response(dashboard.breakdown(request.tenant))


@extend_schema(tags=["dashboard"], parameters=[DAYS], responses=OpenApiTypes.OBJECT)
class WorkloadView(DashboardView):
    permission_classes = [HasPermission("tickets.view_all")]

    def get(self, request):
        return Response({"agents": dashboard.agent_workload(request.tenant, days=_days(request))})


@extend_schema(tags=["dashboard"], responses=OpenApiTypes.OBJECT)
class ActivityView(DashboardView):
    def get(self, request):
        return Response({"events": dashboard.recent_activity(request.tenant)})
