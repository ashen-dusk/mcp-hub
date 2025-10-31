from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
import uuid
import shortuuid

# ── Category: model ──────────────────────────────────────────────────────────────
class Category(models.Model):
    """
    Category model for organizing MCP servers.
    Includes visual metadata like icon and color for UI representation.
    """
    id = models.CharField(primary_key=True, max_length=30, editable=False, unique=True)
    name = models.CharField(max_length=100, unique=True, help_text="Unique category name")
    slug = models.SlugField(max_length=120, unique=True, blank=True, null=True, help_text="URL-friendly slug for category")
    icon = models.TextField(blank=True, null=True, help_text="Icon identifier (URL, emoji, icon name, or icon class)")
    color = models.CharField(max_length=20, blank=True, null=True, help_text="Color code for UI display (hex, rgb, or color name)")
    description = models.TextField(blank=True, null=True, help_text="Description of this category")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "category"
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = f"ctg_{shortuuid.uuid()}"

        # ✅ Added slug generation (new functionality)
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

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
    description = models.TextField(blank=True, null=True, help_text="Description of what this server does")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='servers',
        help_text="Category this server belongs to"
    )
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