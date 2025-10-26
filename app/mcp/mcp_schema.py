"""
GraphQL schema for MCP server operations.

Provides queries and mutations for managing MCP servers,
connections, and retrieving server-specific information.
"""

from typing import List, Optional
import logging

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
    JSON
)
from app.mcp.utils import generate_anonymous_session_key
from app.mcp.oauth_helper import initiate_oauth_flow
from app.mcp.oauth_storage import ClientTokenStorage


def _get_user_context(info: Info) -> str:
    """
    Extract session key from request context.

    For authenticated users, returns their username.
    For anonymous users, generates a session key based on request metadata.

    Args:
        info: GraphQL resolver info object

    Returns:
        Session identifier string
    """
    request = info.context.request
    user = getattr(request, 'user', None)

    # If user is authenticated, use username as session key
    if user and not isinstance(user, AnonymousUser) and user.is_authenticated:
        return user.username

    # For anonymous users, generate session key from request
    return generate_anonymous_session_key(request)

@strawberry.type
# ── graphql: query ───────────────────────────────────────────────────────────
class Query:
    mcp_server_query: List[MCPServerType] = strawberry_django.field(filters=MCPServerFilter)

    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get all public MCP servers with user/session-specific connection states."""
        session_key = _get_user_context(info)
        logging.debug(f"Fetching MCP servers for session: {session_key}")
        servers = await mcp.alist_servers(session_id=session_key)
        return servers

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def get_user_mcp_servers(self, info: Info) -> List[MCPServerType]:
        """Get only the user's own MCP servers with connection status and tools."""
        user = info.context.request.user
        session_key = _get_user_context(info)
        logging.debug(f"Fetching user MCP servers for session: {session_key}")

        servers = [s async for s in MCPServer.objects.filter(owner=user).select_related('owner').order_by("name")]

        # Get user/session-specific connection states from Redis
        for server in servers:
            try:
                server.connection_status = await mcp._get_connection_status(server.name, session_key)
                server.tools = await mcp._get_connection_tools(server.name, session_key)
            except Exception as e:
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
        is_public: Optional[bool] = False, description: Optional[str] = None,
    ) -> MCPServerType:
        # get user from request context
        user = info.context.request.user
        return await mcp.asave_server(
            name, transport, user, url, command, args, headers, query_params,
            requires_oauth2, is_public=is_public, description=description
        )
        
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def remove_mcp_server(self, info: Info, name: str) -> bool:
        # Get user from request context
        user = info.context.request.user
        return await mcp.aremove_server(name, user=user)

    @strawberry.mutation
    async def set_mcp_server_enabled(self, info: Info, name: str, enabled: bool) -> MCPServerType:
        """Enable or disable an MCP server."""
        session_key = _get_user_context(info)
        return await mcp.aset_server_enabled(name=name, enabled=enabled, session_id=session_key)

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        """
        Connect to an MCP server, automatically handling OAuth if required.

        This mutation intelligently handles both OAuth and non-OAuth servers:
        - If OAuth is required and tokens don't exist: Returns auth URL for redirect
        - If OAuth is required and tokens exist: Connects using existing tokens
        - If OAuth is not required: Connects normally

        Frontend should check `requires_auth` and redirect to `authorization_url` if true.
        """
        session_key = _get_user_context(info)
        user = info.context.request.user
        user_id = user.username if user and not isinstance(user, AnonymousUser) and user.is_authenticated else None

        try:
            # Get server from database
            server = await MCPServer.objects.aget(name=name)

            # Check if OAuth is required
            if server.requires_oauth2 and server.url:
                # Check if tokens already exist
                storage = ClientTokenStorage(
                    server_url=server.url,
                    user_id=user_id,
                    session_id=session_key
                )

                try:
                    existing_tokens = await storage.get_tokens()
                except Exception:
                    existing_tokens = None

                # If no tokens exist, initiate OAuth flow
                if not existing_tokens:
                    logging.info(f"[connect_mcp_server] OAuth required for {name}, initiating OAuth flow")
                    success, message, authorization_url, state = await initiate_oauth_flow(
                        server=server,
                        session_id=session_key,
                        user_id=user_id
                    )

                    logging.info(f"[connect_mcp_server] OAuth initiation result - success: {success}, auth_url: {authorization_url[:50] if authorization_url else None}...")

                    if not success:
                        logging.error(f"[connect_mcp_server] OAuth initiation failed: {message}")
                        return ConnectionResult(
                            success=False,
                            message=message,
                            connection_status="FAILED",
                            server=server,
                            requires_auth=True,
                            authorization_url=None,
                            state=None
                        )

                    # Return result with authorization URL for frontend to redirect
                    logging.info(f"[connect_mcp_server] Returning OAuth redirect response with requiresAuth=True")
                    result = ConnectionResult(
                        success=False,  # Not yet connected - need OAuth first
                        message="OAuth authorization required",
                        connection_status="DISCONNECTED",
                        server=server,
                        requires_auth=True,
                        authorization_url=authorization_url,
                        state=state
                    )
                    logging.info(f"[connect_mcp_server] Result: requiresAuth={result.requires_auth}, authUrl={result.authorization_url[:50] if result.authorization_url else None}...")
                    return result
                else:
                    logging.info(f"OAuth tokens exist for {name}, connecting with existing tokens")

            # Either no OAuth required, or OAuth tokens exist - proceed with connection
            success, message, connected_server = await mcp.connect_server(name, session_id=session_key)
            return ConnectionResult(
                success=success,
                message=f"Successfully connected to {name}" if success else message,
                connection_status="CONNECTED" if success else "FAILED",
                server=connected_server or server,
                requires_auth=False,
                authorization_url=None,
                state=None
            )

        except MCPServer.DoesNotExist:
            # Create a minimal server object for error response
            error_server = MCPServer(name=name, transport="", connection_status="FAILED")
            return ConnectionResult(
                success=False,
                message=f"Server {name} not found",
                connection_status="FAILED",
                server=error_server,
                requires_auth=False,
                authorization_url=None,
                state=None
            )
        except Exception as e:
            logging.exception(f"Error connecting to server {name}: {e}")
            try:
                server = await MCPServer.objects.aget(name=name)
            except Exception:
                server = MCPServer(name=name, transport="", connection_status="FAILED")

            return ConnectionResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                connection_status="FAILED",
                server=server,
                requires_auth=False,
                authorization_url=None,
                state=None
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
        """
        Restart MCP server by clearing OAuth tokens and reconnecting.

        This mutation intelligently handles OAuth servers:
        - Clears existing OAuth tokens
        - If OAuth is required: Returns auth URL for re-authorization
        - If OAuth is not required: Reconnects immediately
        """
        session_key = _get_user_context(info)
        user = info.context.request.user
        user_id = user.username if user and not isinstance(user, AnonymousUser) and user.is_authenticated else None

        try:
            # Get server from database
            server = await MCPServer.objects.aget(name=name)

            # Clear OAuth tokens if applicable
            if server.url and server.requires_oauth2:
                try:
                    storage = ClientTokenStorage(
                        server_url=server.url,
                        user_id=user_id,
                        session_id=session_key,
                    )
                    storage.clear()  # Synchronous method
                    logging.info(f"[restart_mcp_server] Cleared OAuth tokens for {name}")
                except Exception as e:
                    logging.warning(f"[restart_mcp_server] Failed to clear tokens for {name}: {e}")

            # If OAuth is required, initiate OAuth flow (since we just cleared tokens)
            if server.requires_oauth2 and server.url:
                logging.info(f"[restart_mcp_server] OAuth required for {name}, initiating OAuth flow")
                success, message, authorization_url, state = await initiate_oauth_flow(
                    server=server,
                    session_id=session_key,
                    user_id=user_id
                )

                if not success:
                    logging.error(f"[restart_mcp_server] OAuth initiation failed: {message}")
                    return ConnectionResult(
                        success=False,
                        message=message,
                        connection_status="FAILED",
                        server=server,
                        requires_auth=True,
                        authorization_url=None,
                        state=None
                    )

                # Return result with authorization URL for frontend to redirect
                logging.info(f"[restart_mcp_server] Returning OAuth redirect response")
                return ConnectionResult(
                    success=False,  # Not yet connected - need OAuth first
                    message="OAuth authorization required for restart",
                    connection_status="DISCONNECTED",
                    server=server,
                    requires_auth=True,
                    authorization_url=authorization_url,
                    state=state
                )

            # Non-OAuth server: proceed with normal reconnection
            success, message, connected_server = await mcp.connect_server(name, session_id=session_key)
            return ConnectionResult(
                success=success,
                message=f"Successfully restarted {name}" if success else message,
                connection_status="CONNECTED" if success else "FAILED",
                server=connected_server or server,
                requires_auth=False,
                authorization_url=None,
                state=None
            )

        except MCPServer.DoesNotExist:
            error_server = MCPServer(name=name, transport="", connection_status="FAILED")
            return ConnectionResult(
                success=False,
                message=f"Server {name} not found",
                connection_status="FAILED",
                server=error_server,
                requires_auth=False,
                authorization_url=None,
                state=None
            )
        except Exception as e:
            logging.exception(f"Error restarting server {name}: {e}")
            try:
                server = await MCPServer.objects.aget(name=name)
            except Exception:
                server = MCPServer(name=name, transport="", connection_status="FAILED")

            return ConnectionResult(
                success=False,
                message=f"Restart failed: {str(e)}",
                connection_status="FAILED",
                server=server,
                requires_auth=False,
                authorization_url=None,
                state=None
            )

