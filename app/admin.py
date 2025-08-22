from django.contrib import admin
from django import forms
from django.db import models
from django_svelte_jsoneditor.widgets import SvelteJSONEditorWidget
from .models import MCPServer, Assistant, Tool


class MCPServerAdminForm(forms.ModelForm):
    class Meta:
        model = MCPServer
        fields = "__all__"
        widgets = {
            "args": SvelteJSONEditorWidget,
            "headers": SvelteJSONEditorWidget,
            "query_params": SvelteJSONEditorWidget,
            "tools": SvelteJSONEditorWidget,
        }


@admin.register(MCPServer)
class MCPServerAdmin(admin.ModelAdmin):
    form = MCPServerAdminForm
    list_display = ("name", "transport", "enabled", "connection_status", "updated_at")
    search_fields = ("name", "transport")
    list_filter = ("transport", "enabled", "connection_status")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Assistant)
class AssistantAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": SvelteJSONEditorWidget},
    }
    list_display = ("id", "name", "type", "is_active", "created_at")
    search_fields = ("name", "type")
    list_filter = ("type", "is_active")
    readonly_fields = ("id", "created_at", "updated_at")

@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": SvelteJSONEditorWidget},
    }
    list_display = ("id", "name", "assistant", "category", "is_active", "updated_at")
    search_fields = ("name", "category")
    list_filter = ("category", "is_active", "assistant")
    readonly_fields = ("id", "created_at", "updated_at")