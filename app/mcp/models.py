from django.db import models
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
    name = models.CharField(max_length=100, unique=True)
    transport = models.CharField(max_length=32, choices=TRANSPORT_CHOICES)
    url = models.TextField(blank=True, null=True)
    command = models.TextField(blank=True, null=True)
    
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

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.transport})"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"mcp_{shortuuid.uuid()}"
        super().save(*args, **kwargs)

