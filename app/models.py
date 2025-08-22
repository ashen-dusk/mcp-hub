import shortuuid
from django.db import models
from .mcp.models import MCPServer

__all__ = ["MCPServer", "Agent", "Tool"]


# ── Agent: model ─────────────────────────────────────────────────────────────
class Assistant(models.Model):
    """
    Represents a registered AI agent (like ResearchAgent, SupportAgent, etc.)
    """
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    name = models.CharField(max_length=100, unique=True)   # e.g., "Research Agent"
    type = models.CharField(max_length=50)                 # e.g., "research", "support"
    description = models.TextField(blank=True, null=True)  # human-readable desc
    is_active = models.BooleanField(default=True)

    # optional agent-specific config (API keys, model params, prompts, etc.)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.type})"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"assistant_{shortuuid.uuid()[:8]}"
        super().save(*args, **kwargs)

# ── Tool: model ─────────────────────────────────────────────────────────────
class Tool(models.Model):
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    assistant = models.ForeignKey(
        Assistant,
        related_name="tools",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The agent this tool belongs to (required for active tools)"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=50)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assistant", "name"], 
                name="unique_tool_per_assistant"
            ),
            models.CheckConstraint(
               check=~(models.Q(is_active=True) & models.Q(assistant__isnull=True)),
               name="active_tool_requires_assistant"
            ),
        ]

    def __str__(self):
        assistant_name = self.assistant.name if self.assistant else "Unassigned"
        return f"{self.name} ({self.category}) for {assistant_name}"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"tool_{shortuuid.uuid()[:8]}"
        super().save(*args, **kwargs)
