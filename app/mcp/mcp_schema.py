from typing import List, Optional

import strawberry
import strawberry_django
from strawberry.types import Info

from app.graphql.permissions import IsAuthenticated
from app.mcp.manager import mcp
from app.mcp.models import MCPServer
from app.mcp.types import (
    MCPServerType, 
    MCPServerFilter,
    ConnectionResult, 
    DisconnectResult, 
    ToolInfo,
    JSON
)

@strawberry.type
# ── graphql: query ───────────────────────────────────────────────────────────
class Query:
    mcp_servers: List[MCPServerType] = strawberry_django.field(filters=MCPServerFilter)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def get_user_mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get only the user's own MCP servers."""
        user = info.context.request.user
        return [s async for s in MCPServer.objects.filter(owner=user).select_related('owner').order_by("name")]


@strawberry.type
# ── graphql: mutation ────────────────────────────────────────────────────────
class Mutation:
    
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def save_mcp_server(
        self, info: Info, name: str, transport: str,
        url: Optional[str] = None, command: Optional[str] = None,
        args: Optional[JSON] = None, headers: Optional[JSON] = None,
        query_params: Optional[JSON] = None, requires_oauth2: Optional[bool] = False,
        is_public: Optional[bool] = False,
    ) -> MCPServerType:
        # get user from request context
        user = info.context.request.user
        return await mcp.asave_server(
            name, transport, user, url, command, args, headers, query_params, 
            requires_oauth2, is_public=is_public
        )
        
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def remove_mcp_server(self, info: Info, name: str) -> bool:
        # Get user from request context
        user = info.context.request.user
        return await mcp.aremove_server(name, user=user)

    @strawberry.mutation
    async def set_mcp_server_enabled(self, info: Info, name: str, enabled: bool) -> MCPServerType:
        return await mcp.aet_server_enabled(name=name, enabled=enabled)

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        success, message, server = await mcp.connect_server(name)
        return ConnectionResult(
            success=success,
            message=f"Successfully connected to {name}" if success else message,
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )

    @strawberry.mutation
    async def disconnect_mcp_server(self, info: Info, name: str) -> DisconnectResult:
        success, message, server = await mcp.disconnect_server(name)
        return DisconnectResult(
            success=success,
            message=message,
            server=server,
        )

    @strawberry.mutation
    async def restart_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        status, server = await mcp.arestart_mcp_server(name)
        success = status == "OK"
        return ConnectionResult(
            success=success,
            message=f"Successfully restarted {name}" if success else f"restart failed: {status}",
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )
    
