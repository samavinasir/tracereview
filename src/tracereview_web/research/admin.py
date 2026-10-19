from django.contrib import admin

from .models import ResearchRun


@admin.register(ResearchRun)
class ResearchRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("id", "error")
    readonly_fields = ("id", "status", "progress", "error", "created_at", "updated_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
