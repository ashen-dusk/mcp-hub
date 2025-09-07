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
        print(f"[DEBUG] Authenticated user: {user.username}")
        return user, None
    
    # For anonymous users, create a unique session key based on request characteristics
    # This avoids Django session creation in async context
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:50]
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    
    # Create a unique identifier for this anonymous session
    session_identifier = f"{ip}_{user_agent}_{forwarded_for}"
    session_key = f"anon_{hash(session_identifier)}"
    
    print(f"[DEBUG] Anonymous session key: {session_key}")
    print(f"[DEBUG] Final context - user: {user}, session_key: {session_key}")
    return None, session_key

@strawberry.type
# ── graphql: query ───────────────────────────────────────────────────────────
class Query:
    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get all public MCP servers with user/session-specific connection states."""
        user, session_key = _get_user_context(info)
        servers = await mcp.alist_servers(user=user, session_key=session_key)
        return servers

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
        user, session_key = _get_user_context(info)
        return await mcp.aet_server_enabled(name=name, enabled=enabled, user=user, session_key=session_key)

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        user, session_key = _get_user_context(info)
        success, message, server = await mcp.connect_server(name, user=user, session_key=session_key)
        return ConnectionResult(
            success=success,
            message=f"Successfully connected to {name}" if success else message,
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )

    @strawberry.mutation
    async def disconnect_mcp_server(self, info: Info, name: str) -> DisconnectResult:
        user, session_key = _get_user_context(info)
        success, message, server = await mcp.disconnect_server(name, user=user, session_key=session_key)
        return DisconnectResult(
            success=success,
            message=message,
            server=server,
        )

    @strawberry.mutation
    async def restart_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        user, session_key = _get_user_context(info)
        status, server = await mcp.arestart_mcp_server(name, user=user, session_key=session_key)
        success = status == "OK"
        return ConnectionResult(
            success=success,
            message=f"Successfully restarted {name}" if success else f"restart failed: {status}",
            connection_status="CONNECTED" if success else "FAILED",
            server=server,
        )
    
