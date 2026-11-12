from django.contrib import admin

from .models import AIAnalysis, AIInsight, AIRecommendation


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "status", "provider", "model", "confidence", "is_mock", "ticket")
    list_filter = ("kind", "status", "provider", "is_mock")
    readonly_fields = [f.name for f in AIAnalysis._meta.fields]


@admin.register(AIRecommendation)
class AIRecommendationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "type", "status", "confidence", "ticket", "decided_by")
    list_filter = ("type", "status")


@admin.register(AIInsight)
class AIInsightAdmin(admin.ModelAdmin):
    list_display = ("created_at", "type", "title", "is_dismissed")
