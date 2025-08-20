from django.db import models


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

    name = models.CharField(max_length=100, unique=True)
    transport = models.CharField(max_length=32, choices=TRANSPORT_CHOICES)
    url = models.TextField(blank=True, null=True)
    command = models.TextField(blank=True, null=True)
    args_json = models.TextField(blank=True, null=True)
    headers_json = models.TextField(blank=True, null=True)
    query_params_json = models.TextField(blank=True, null=True)
    enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_server"
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.transport})"

