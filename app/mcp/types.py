import strawberry
from strawberry import auto, ID
import strawberry_django
from datetime import datetime
from typing import Optional, List, Dict, Any
from strawberry.scalars import JSON
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from strawberry.relay.types import Node

from .models import MCPServer, Category
from .utils import generate_anonymous_session_key
from strawberry.types import Info

# ── graphql: types ────────────────────────────────────────────────────────────
@strawberry_django.filter_type(Category, lookups=True)
class CategoryFilter:
    id: auto
    name: auto

@strawberry_django.order_type(Category)
class CategoryOrder:
    name: auto
    created_at: auto
    updated_at: auto

@strawberry_django.type(Category, filters=CategoryFilter, order=CategoryOrder, pagination=True)
class CategoryType(Node):
    id: ID
    name: str
    icon: Optional[str]
    color: Optional[str]
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    @strawberry_django.field
    async def servers(self, root: Category) -> List["MCPServerType"]:
        """Get all MCP servers that belong to this category."""
        @sync_to_async
        def get_servers():
            return list(root.servers.all().select_related('owner'))
        return await get_servers()


@strawberry.type
class ToolInfo:
    name: str
    description: Optional[str]
    schema: JSON

@strawberry_django.filter_type(MCPServer, lookups=True)
class MCPServerFilter:
    id: auto
    name: auto
    transport: auto
    enabled: auto
    requires_oauth2: auto
    connection_status: auto
    is_public: auto
    category: Optional[CategoryFilter]

@strawberry_django.order_type(MCPServer)
class MCPServerOrder:
    name: auto
    created_at: auto
    updated_at: auto

@strawberry_django.type(MCPServer, filters=MCPServerFilter, order=MCPServerOrder, pagination=True)
class MCPServerType(Node):
    id: ID
    name: str
    description: Optional[str]
    transport: str
    url: Optional[str]
    command: Optional[str]
    args: Optional[JSON]
    enabled: bool
    requires_oauth2: bool
    updated_at: datetime
    created_at: datetime
    is_public: bool

    @strawberry_django.field
    async def category(self, root: MCPServer) -> Optional[CategoryType]:
        """Get the category for this server."""
        @sync_to_async
        def get_category():
            return root.category
        category = await get_category()
        return category

    @strawberry.field
    async def owner(self, root: MCPServer) -> Optional[str]:
        @sync_to_async
        def get_owner_username():
            return root.owner.username if root.owner else None
        return await get_owner_username()

    @strawberry.field
    async def connection_status(self, root: "MCPServer", info: Info) -> str:
        """Get session-specific connection status from Redis."""
        from .manager import mcp

        # Extract session key from context
        request = info.context.request
        user = getattr(request, 'user', None)

        if user and not isinstance(user, AnonymousUser) and user.is_authenticated:
            session_key = user.username
        else:
            session_key = generate_anonymous_session_key(request)

        try:
            return await mcp._get_connection_status(root.name, session_key)
        except Exception:
            return "DISCONNECTED"

    @strawberry.field
    async def tools(self, root: "MCPServer", info: Info) -> List["ToolInfo"]:
        """Get session-specific tools from Redis or fallback to database."""
        from .manager import mcp

        # Extract session key from context
        request = info.context.request
        user = getattr(request, 'user', None)

        if user and not isinstance(user, AnonymousUser) and user.is_authenticated:
            session_key = user.username
        else:
            session_key = generate_anonymous_session_key(request)

        try:
            # Try to get tools from Redis (session-specific)
            redis_tools = await mcp._get_connection_tools(root.name, session_key)
            if redis_tools:
                return [
                    ToolInfo(
                        name=tool.get("name", ""),
                        description=tool.get("description", ""),
                        schema=tool.get("schema", "{}"),
                    )
                    for tool in redis_tools
                    if isinstance(tool, dict)
                ]
        except Exception:
            pass

        # Fallback to database tools
        return [
            ToolInfo(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                schema=tool.get("schema", "{}"),
            )
            for tool in (root.tools or [])
            if isinstance(tool, dict)
        ]

@strawberry.type
class ConnectionResult:
    success: bool
    message: str
    connection_status: str
    server: MCPServerType
    requires_auth: bool = False
    authorization_url: Optional[str] = None
    state: Optional[str] = None

@strawberry.type
class DisconnectResult:
    success: bool
    message: str
    server: MCPServerType
