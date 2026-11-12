from django.contrib import admin

from .models import KnowledgeArticle


@admin.register(KnowledgeArticle)
class KnowledgeArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "source", "category", "updated_at")
    list_filter = ("status", "source")
    search_fields = ("title", "body")
