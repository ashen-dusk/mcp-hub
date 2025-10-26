import strawberry
from strawberry import auto, ID
import strawberry_django
from datetime import datetime
from typing import Optional, List, Dict, Any
from strawberry.scalars import JSON
from .models import MCPServer
from asgiref.sync import sync_to_async

# ── graphql: types ────────────────────────────────────────────────────────────
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

@strawberry_django.type(MCPServer, filters=MCPServerFilter)
class MCPServerType:
    id: ID
    name: str
    description: Optional[str]
    transport: str
    url: Optional[str]
    command: Optional[str]
    args: Optional[JSON]
    enabled: bool
    requires_oauth2: bool
    connection_status: str
    updated_at: datetime
    created_at: datetime
    is_public: bool

    @strawberry.field
    async def owner(self, root: MCPServer) -> Optional[str]:
        @sync_to_async
        def get_owner_username():
            return root.owner.username if root.owner else None
        return await get_owner_username()

    @strawberry.field
    def tools(self, root: "MCPServer") -> List["ToolInfo"]:
        """Resolve JSONField `tools` into a list of ToolInfo objects."""
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
