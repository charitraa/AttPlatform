from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/summary/", views.SummaryView.as_view(), name="dashboard-summary"),
    path("dashboard/trends/", views.TrendsView.as_view(), name="dashboard-trends"),
    path("dashboard/breakdown/", views.BreakdownView.as_view(), name="dashboard-breakdown"),
    path("dashboard/workload/", views.WorkloadView.as_view(), name="dashboard-workload"),
    path("dashboard/activity/", views.ActivityView.as_view(), name="dashboard-activity"),
]
