from typing import List, Optional

import strawberry
import strawberry_django
from strawberry.types import Info

from app.graphql.permissions import IsAuthenticated
from app.mcp.manager import mcp
from app.mcp.models import MCPServer
from django.contrib.auth.models import AnonymousUser, User
from app.mcp.types import (
    MCPServerType, 
    MCPServerFilter,
    ConnectionResult, 
    DisconnectResult, 
    ToolInfo,
    JSON
)

def _get_user_context(info: Info) -> tuple[Optional[User], Optional[str]]:
    """Extract user and session key from request context."""
    request = info.context.request
    user = getattr(request, 'user', None)
    
    # If user is authenticated, return user
    if user and not isinstance(user, AnonymousUser) and user.is_authenticated:
        return user
    
    # For anonymous users, create a unique session key based on request characteristics
    # This avoids Django session creation in async context
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:50]
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    
    # Create a unique identifier for this anonymous session
    session_identifier = f"{ip}_{user_agent}_{forwarded_for}"
    session_key = f"anon_{hash(session_identifier)}"
    
    return session_key

@strawberry.type
# ── graphql: query ───────────────────────────────────────────────────────────
class Query:
    mcp_server_query: List[MCPServerType] = strawberry_django.field(filters=MCPServerFilter)

    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get all public MCP servers with user/session-specific connection states."""
        session_key = _get_user_context(info)
        print(f"DEBUG: user in mcp_servers: {session_key}")
        servers = await mcp.alist_servers(session_id=session_key)
        return servers

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def get_user_mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get only the user's own MCP servers with connection status and tools."""
        user = info.context.request.user
        session_key = _get_user_context(info)
        print(f"DEBUG: user in get_user_mcp_servers: {session_key}")

        servers = [s async for s in MCPServer.objects.filter(owner=user).select_related('owner').order_by("name")]

        # Get user/session-specific connection states from Redis
        for server in servers:
            try:
                server.connection_status = await mcp._get_connection_status(server.name, session_key)
                server.tools = await mcp._get_connection_tools(server.name, session_key)
            except Exception as e:
                import logging
                logging.warning(f"Failed to get connection state for server {server.name}: {e}")
                server.connection_status = "DISCONNECTED"
                server.tools = []

        return servers


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
        session_key = _get_user_context(info)
        return await mcp.aet_server_enabled(name=name, enabled=enabled, session_id=session_key)

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        session_key = _get_user_context(info)
        success, message, server = await mcp.connect_server(name, session_id=session_key)
        return ConnectionResult(
            success=success,
            message=f"Successfully connected to {name}" if success else message,
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )

    @strawberry.mutation
    async def disconnect_mcp_server(self, info: Info, name: str) -> DisconnectResult:
        session_key = _get_user_context(info)
        success, message, server = await mcp.disconnect_server(name, session_id=session_key)
        return DisconnectResult(
            success=success,
            message=message,
            server=server,
        )

    @strawberry.mutation
    async def restart_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        session_key = _get_user_context(info)
        status, server = await mcp.arestart_mcp_server(name, session_id=session_key)
        success = status == "OK"
        return ConnectionResult(
            success=success,
            message=f"Successfully restarted {name}" if success else f"restart failed: {status}",
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )
    
