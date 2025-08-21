import shortuuid
from django.db import models
from .mcp.models import MCPServer

__all__ = ["MCPServer", "Agent", "Tool"]


# ── Agent: model ─────────────────────────────────────────────────────────────
class Agent(models.Model):
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
            self.id = f"agt_{shortuuid.uuid()[:8]}"
        super().save(*args, **kwargs)

# ── Tool: model ─────────────────────────────────────────────────────────────
class Tool(models.Model):
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    agent = models.ForeignKey(
        Agent,
        related_name="tools",
        on_delete=models.CASCADE,
        help_text="The agent this tool belongs to"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=50)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["agent", "name"], name="unique_tool_per_agent")
        ]

    def __str__(self):
        return f"{self.name} ({self.type}) for {self.agent.name}"
