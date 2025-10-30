import shortuuid
from django.db import models
from django.contrib.auth.models import User
from .mcp.models import MCPServer, Category

__all__ = ["MCPServer", "Category", "Assistant"]


# ── Assistant: model ─────────────────────────────────────────────────────────────
class Assistant(models.Model):
    """
    Represents a user's personalized AI assistant with custom instructions.
    Similar to ChatGPT/Claude custom instructions - users can customize their assistant's behavior.
    """
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    user = models.ForeignKey(
        User,
        related_name="assistants",
        on_delete=models.CASCADE,
        null=True,  # Temporarily nullable for migration
        blank=True,
        help_text="The user who owns this assistant"
    )
    name = models.CharField(max_length=100, default="My Assistant")  # Display name, user can change anytime
    description = models.TextField(blank=True, null=True)  # Optional description
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Custom instructions to control the assistant's behavior, tone, and responses"
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this assistant is currently active. Only one assistant can be active per user."
    )
    # optional assistant-specific config (model preferences, etc.)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (by {self.user.username})"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"assistant_{shortuuid.uuid()[:8]}"

        # Ensure only one assistant is active per user
        if self.is_active and self.user:
            # Deactivate all other assistants for this user
            Assistant.objects.filter(user=self.user, is_active=True).exclude(id=self.id).update(is_active=False)

        super().save(*args, **kwargs)
