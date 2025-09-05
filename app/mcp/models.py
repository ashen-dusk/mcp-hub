from django.db import models
from django.contrib.auth.models import User
import uuid
import shortuuid

# ── MCPServer: model ─────────────────────────────────────────────────────────────
class MCPServer(models.Model):
    TRANSPORT_STDIO = "stdio"
    TRANSPORT_STREAMABLE_HTTP = "streamable_http"
    TRANSPORT_SSE = "sse"
    TRANSPORT_WEBSOCKET = "websocket"

    TRANSPORT_CHOICES = [
        (TRANSPORT_STDIO, "stdio"),
        (TRANSPORT_STREAMABLE_HTTP, "streamable_http"),
        (TRANSPORT_SSE, "sse"),
        (TRANSPORT_WEBSOCKET, "websocket"),
    ]

    CONNECTION_STATUS_CHOICES = [
        ("CONNECTED", "Connected"),
        ("DISCONNECTED", "Disconnected"),
        ("FAILED", "Failed"),
    ]

    # ── django: field ────────────────────────────────────────────────────────────
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    name = models.CharField(max_length=100)
    transport = models.CharField(max_length=32, choices=TRANSPORT_CHOICES)
    url = models.TextField(blank=True, null=True)
    command = models.TextField(blank=True, null=True)
    
    # User ownership and sharing
    owner = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="User who owns this server. Null means it's a shared server."
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this server is public and available to all users"
    )
    
    # json fields
    args = models.JSONField(default=dict, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    query_params = models.JSONField(default=dict, blank=True)
    tools = models.JSONField(default=list, blank=True)

    # ── django: connection status fields ───────────────────────────────────────
    enabled = models.BooleanField(default=True)
    requires_oauth2 = models.BooleanField(
    default=False,
    help_text="Indicates whether this MCP server requires OAuth for authentication."
    )
    connection_status = models.CharField(
        max_length=16,
        choices=CONNECTION_STATUS_CHOICES,
        default="DISCONNECTED"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── django: meta ────────────────────────────────────────────────────────────
    class Meta:
        db_table = "mcp_server"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], 
                name="unique_server_name_per_user",
                condition=models.Q(owner__isnull=False)
            ),
            models.UniqueConstraint(
                fields=["name"], 
                name="unique_shared_server_name",
                condition=models.Q(is_public=True)
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.transport})"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"mcp_{shortuuid.uuid()}"
        super().save(*args, **kwargs)
    
    @property
    def is_user_owned(self) -> bool:
        """Check if this server is owned by a specific user."""
        return self.owner is not None
    
    @property
    def is_publicly_available(self) -> bool:
        """Check if this server is public and available to all users."""
        return self.is_public
    
    def can_be_accessed_by(self, user: User) -> bool:
        """Check if a user can access this server."""
        if self.is_publicly_available:
            return True
        if self.owner == user:
            return True
        return False

