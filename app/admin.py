from django.contrib import admin
from .models import MCPServer


@admin.register(MCPServer)
class MCPServerAdmin(admin.ModelAdmin):
    list_display = ("name", "transport", "enabled", "created_at", "updated_at")
    list_filter = ("transport", "enabled")
    search_fields = ("name", "url", "command")
    readonly_fields = ("id", "created_at", "updated_at",)

    # :: TODO: add fieldsets
    # fieldsets = (
    #     (None, {"fields": ("name", "transport", "enabled")}),
    #     ("Connection", {"fields": ("url", "command", "args_json", "headers_json", "query_params_json")}),
    #     ("Timestamps", {"fields": ("created_at", "updated_at")}),
    # )
