"""
MCP Server Manager - Core business logic for MCP server operations.

Handles server lifecycle, connection management, tool retrieval,
and session-isolated server interactions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple

from langchain_mcp_adapters.client import MultiServerMCPClient
from django.contrib.auth.models import User
from fastmcp.client import Client as FastMCPClient
from fastmcp.client.auth.oauth import FileTokenStorage

from .models import MCPServer
from .redis_manager import mcp_redis
from .oauth_storage import ClientTokenStorage, ClientOAuth
from .utils import patch_tools_schema, serialize_tools
from .adapter_builder import MCPAdapterBuilder
from .constants import (
    MCP_CLIENT_TIMEOUT,
    TOOL_FETCH_TIMEOUT,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_FAILED,
    RESULT_OK,
    RESULT_ERROR,
    RESULT_TIMEOUT,
    RESULT_NOT_FOUND,
    RESULT_DISABLED,
    OAUTH_CLIENT_NAME,
    OAUTH_CALLBACK_PORT,
    OAUTH_DEFAULT_SCOPES,
)


# Module-level singleton for adapter building (stateless, efficient)
_adapter_builder = MCPAdapterBuilder()


class MCPServerManager:
    """
    Manages MCP server connections and operations.

    Provides session-isolated connection management to prevent
    cross-user data leakage in multi-tenant environments.
    """

    def __init__(self):
        """Initialize the MCP manager."""
        self.client: Optional[MultiServerMCPClient] = None
        self.adapter_map: Dict[str, Dict[str, Any]] = {}
        self.tools: List[Any] = []
        # Track server configs (not actual client instances)
        self.server_configs: Dict[str, Dict[str, Any]] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Redis State Management (Delegates to redis_manager)
    # ──────────────────────────────────────────────────────────────────────

    async def _get_connection_status(
        self, server_name: str, session_id: Optional[str] = None
    ) -> str:
        """Get connection status from Redis."""
        connection_status = await mcp_redis.get_connection_status(
            server_name, session_id
        )
        logging.debug(
            f"Connection status for {server_name} (session: {session_id}): {connection_status}"
        )
        return connection_status

    async def _get_connection_tools(
        self, server_name: str, session_id: Optional[str] = None
    ) -> List[Dict]:
        """Get connection tools from Redis."""
        return await mcp_redis.get_connection_tools(server_name, session_id)

    async def _set_connection_status(
        self,
        server_name: str,
        status: str,
        tools: Optional[List[Dict]] = None,
        session_id: Optional[str] = None,
    ):
        """Set connection status in Redis."""
        await mcp_redis.set_connection_status(server_name, status, tools, session_id)

    # ──────────────────────────────────────────────────────────────────────
    # Server CRUD Operations
    # ──────────────────────────────────────────────────────────────────────

    async def alist_servers(
        self, session_id: Optional[str] = None
    ) -> List[MCPServer]:
        """
        Get all public servers with session-specific connection status.

        Args:
            session_id: Session identifier for isolated state

        Returns:
            List of MCPServer instances with connection status and tools
        """
        servers = [
            s
            async for s in MCPServer.objects.filter(is_public=True).order_by("name")
        ]

        # Enrich with session-specific connection states from Redis
        for server in servers:
            try:
                server.connection_status = await self._get_connection_status(
                    server.name, session_id
                )
                server.tools = await self._get_connection_tools(
                    server.name, session_id
                )
            except Exception as e:
                logging.warning(
                    f"Failed to get connection state for server {server.name}: {e}"
                )
                server.connection_status = STATUS_DISCONNECTED
                server.tools = []

        return servers

    async def asave_server(
        self,
        name: str,
        transport: str,
        owner: User,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[dict] = None,
        headers: Optional[dict] = None,
        query_params: Optional[dict] = None,
        requires_oauth2: Optional[bool] = False,
        is_public: Optional[bool] = False,
    ) -> MCPServer:
        """
        Create or update an MCP server configuration.

        Args:
            name: Server name
            transport: Transport type (stdio, sse, etc.)
            owner: User who owns this server
            url: Server URL (for network transports)
            command: Command to execute (for stdio)
            args: Command arguments
            headers: HTTP headers
            query_params: URL query parameters
            requires_oauth2: Whether OAuth2 is required
            is_public: Whether server is publicly available

        Returns:
            Created or updated MCPServer instance
        """
        rec, _ = await MCPServer.objects.aupdate_or_create(
            name=name,
            owner=owner,
            defaults={
                "transport": transport,
                "url": url,
                "command": command,
                "args": args or {},
                "headers": headers or {},
                "query_params": query_params or {},
                "enabled": True,
                "requires_oauth2": requires_oauth2,
                "is_public": is_public,
            },
        )
        await self.initialize_client()  # Refresh global client if needed
        return rec

    async def aremove_server(
        self, name: str, user: User, session_id: Optional[str] = None
    ) -> bool:
        """
        Remove an MCP server and clean up OAuth tokens.

        Args:
            name: Server name
            user: User who owns the server
            session_id: Session identifier

        Returns:
            True if server was deleted, False otherwise
        """
        try:
            rec = await MCPServer.objects.filter(name=name, owner=user).afirst()

            if not rec:
                return False

            # Clear OAuth tokens if applicable
            if rec.url and rec.requires_oauth2:
                try:
                    storage = ClientTokenStorage(
                        server_url=rec.url,
                        user_id=user.username if user else None,
                        session_id=session_id,
                    )
                    await storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear tokens for {name}: {e}")

            await rec.adelete()

            # Clear from server configs
            self.server_configs.pop(name, None)

            await self.initialize_client()
            return True

        except MCPServer.DoesNotExist:
            return False

    async def aset_server_enabled(
        self, name: str, enabled: bool, session_id: Optional[str] = None
    ) -> MCPServer:
        """
        Enable or disable an MCP server.

        Args:
            name: Server name
            enabled: Whether server should be enabled
            session_id: Session identifier

        Returns:
            Updated MCPServer instance
        """
        try:
            rec = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            raise ValueError(f"MCPServer with name '{name}' not found.")

        rec.enabled = enabled
        await rec.asave(update_fields=["enabled", "updated_at"])

        # Disconnect all sessions if disabling
        if not enabled:
            await self._set_connection_status(
                rec.name, STATUS_DISCONNECTED, session_id=session_id
            )
            self.server_configs.pop(name, None)

        await self.initialize_client()
        return rec

    # ──────────────────────────────────────────────────────────────────────
    # Adapter Map Building (Delegated to MCPAdapterBuilder)
    # ──────────────────────────────────────────────────────────────────────

    async def _build_adapter_map(
        self,
        names: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build adapter configuration map for specified servers.

        Delegates to the module-level adapter builder singleton.

        Args:
            names: List of server names to include (None = empty map)
            session_id: Session identifier for OAuth token isolation
            user_id: User identifier for OAuth token isolation

        Returns:
            Dictionary mapping server names to adapter configs
        """
        return await _adapter_builder.build_adapter_map(names, session_id, user_id)

    # ──────────────────────────────────────────────────────────────────────
    # Global Client Initialization (for shared tool access)
    # ──────────────────────────────────────────────────────────────────────

    async def initialize_client(self):
        """
        Initialize global MultiServerMCPClient.

        This is used for shared tool access across all connected servers.
        Note: For session-isolated operations, use aget_tools() instead.
        """
        connected_names = list(self.server_configs.keys())
        self.adapter_map = await self._build_adapter_map(names=connected_names)

        if not self.adapter_map:
            self.client = None
            self.tools = []
            return

        try:
            logging.debug(
                f"Initializing MCP client with adapter map: {self.adapter_map}"
            )
            self.client = MultiServerMCPClient(self.adapter_map)
            raw_tools = await asyncio.wait_for(
                self.client.get_tools(), timeout=TOOL_FETCH_TIMEOUT
            )
            self.tools = patch_tools_schema(raw_tools)

        except asyncio.TimeoutError:
            logging.warning("MCP client initialization or tool fetching timed out.")
            self.client = None
            self.tools = []
        except Exception as e:
            logging.exception(f"Failed to initialize MCP client: {e}")
            if "SSEError" in str(e) or "text/event-stream" in str(e):
                logging.warning(
                    "SSE transport error detected, check server configuration"
                )
            self.client = None
            self.tools = []

    # ──────────────────────────────────────────────────────────────────────
    # Server Connection Operations (Session-Isolated)
    # ──────────────────────────────────────────────────────────────────────

    async def connect_server(
        self, name: str, session_id: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MCPServer]]:
        """
        Connect to a specific MCP server using FastMCP client.

        Args:
            name: Server name
            session_id: Session identifier for isolation

        Returns:
            Tuple of (success, message, server_instance)
        """
        try:
            logging.debug(f"Connecting to {name} for session {session_id}")
            server = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            return False, "Server not found", None

        if not server.url:
            return False, "Server URL is not configured", server

        if FastMCPClient is None:
            return False, "FastMCP client is not available", server

        try:
            # Attempt connection with optional OAuth
            tools_objs = await self._connect_and_fetch_tools(
                server, session_id
            )

            # Serialize and store tools
            tools = patch_tools_schema(tools_objs)
            tools_info = serialize_tools(tools)

            # Update session-specific connection in Redis
            await self._set_connection_status(
                server.name, STATUS_CONNECTED, tools_info, session_id
            )

            # Track server config (not actual client)
            self.server_configs[server.name] = {"url": server.url}

            # Update server object for return
            server.connection_status = STATUS_CONNECTED
            server.tools = tools_info

            return True, "Connected successfully", server

        except asyncio.TimeoutError:
            await self._set_connection_status(
                server.name, STATUS_FAILED, [], session_id
            )
            server.connection_status = STATUS_FAILED
            server.tools = []
            return False, "Connection timeout", server

        except Exception as e:
            await self._set_connection_status(
                server.name, STATUS_FAILED, [], session_id
            )
            server.connection_status = STATUS_FAILED
            server.tools = []
            return False, f"Connection failed: {str(e)}", server

    async def _connect_and_fetch_tools(
        self, server: MCPServer, session_id: Optional[str]
    ) -> List[Any]:
        """
        Connect to server and fetch tools (with or without OAuth).

        Args:
            server: MCPServer instance
            session_id: Session identifier

        Returns:
            List of tool objects
        """
        if server.requires_oauth2:
            oauth = ClientOAuth(
                mcp_url=server.url,
                user_id=None,  # Could extract from server.owner if needed
                session_id=session_id,
                client_name=OAUTH_CLIENT_NAME,
                callback_port=OAUTH_CALLBACK_PORT,
                scopes=OAUTH_DEFAULT_SCOPES,
            )
            async with FastMCPClient(server.url, auth=oauth) as client:
                await asyncio.wait_for(client.ping(), timeout=MCP_CLIENT_TIMEOUT)
                return await asyncio.wait_for(
                    client.list_tools(), timeout=TOOL_FETCH_TIMEOUT
                )
        else:
            async with FastMCPClient(server.url) as client:
                await asyncio.wait_for(client.ping(), timeout=MCP_CLIENT_TIMEOUT)
                return await asyncio.wait_for(
                    client.list_tools(), timeout=TOOL_FETCH_TIMEOUT
                )

    async def disconnect_server(
        self, name: str, session_id: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MCPServer]]:
        """
        Disconnect from a specific MCP server.

        Args:
            name: Server name
            session_id: Session identifier

        Returns:
            Tuple of (success, message, server_instance)
        """
        try:
            try:
                server = await MCPServer.objects.aget(name=name)
            except MCPServer.DoesNotExist:
                return False, "Server not found", None

            # Verify current connection status
            current_status = await self._get_connection_status(server.name, session_id)
            if current_status != STATUS_CONNECTED:
                return False, "Server not connected", server

            # Update session-specific connection status
            await self._set_connection_status(
                server.name, STATUS_DISCONNECTED, [], session_id
            )

            # Update server object for return
            server.connection_status = STATUS_DISCONNECTED
            server.tools = []

            return True, "Disconnected successfully", server

        except Exception as e:
            logging.exception(f"Failed to disconnect from server {name}: {e}")
            try:
                server = await MCPServer.objects.aget(name=name)
                return False, f"Disconnect failed: {str(e)}", server
            except MCPServer.DoesNotExist:
                return False, f"Disconnect failed: {str(e)}", None

    async def arestart_mcp_server(
        self, name: str, session_id: Optional[str] = None
    ) -> Tuple[str, Optional[MCPServer]]:
        """
        Restart server connection (clear OAuth tokens and reconnect).

        Args:
            name: Server name
            session_id: Session identifier

        Returns:
            Tuple of (status_code, server_instance)
        """
        try:
            server = await MCPServer.objects.aget(name=name)

            # Clear OAuth tokens if applicable
            if server.url and server.requires_oauth2:
                try:
                    storage = ClientTokenStorage(
                        server_url=server.url,
                        user_id=None,
                        session_id=session_id,
                    )
                    await storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear tokens for {name}: {e}")

        except MCPServer.DoesNotExist:
            return RESULT_NOT_FOUND, None

        if not server.enabled:
            return RESULT_DISABLED, server

        # Attempt to reconnect
        try:
            tools_objs = await self._connect_and_fetch_tools(server, session_id)
            tools = patch_tools_schema(tools_objs)
            tools_info = serialize_tools(tools)

            # Update session-specific connection
            await self._set_connection_status(
                server.name, STATUS_CONNECTED, tools_info, session_id
            )

            server.tools = tools_info
            server.connection_status = STATUS_CONNECTED

            return RESULT_OK, server

        except asyncio.TimeoutError:
            return RESULT_TIMEOUT, server
        except Exception as e:
            logging.warning(f"Health check for {name} failed: {e}")
            return RESULT_ERROR, server

    # ──────────────────────────────────────────────────────────────────────
    # Session-Isolated Tool Retrieval (No Global State Mutation)
    # ──────────────────────────────────────────────────────────────────────

    async def aget_tools(self, session_id: Optional[str] = None) -> List[Any]:
        """
        Get tool objects for servers connected in this session.

        This creates a throwaway client scoped to the session to avoid
        global state mutation and cross-user leakage.

        Args:
            session_id: Session identifier

        Returns:
            List of tool objects for connected servers
        """
        try:
            # Determine which servers are connected for this session
            connected_names: List[str] = []
            qs = MCPServer.objects.filter(enabled=True, is_public=True)

            async for rec in qs:
                try:
                    status = await self._get_connection_status(rec.name, session_id)
                    if status == STATUS_CONNECTED:
                        connected_names.append(rec.name)
                except Exception:
                    # Ignore lookup failures for individual servers
                    pass

            if not connected_names:
                return []

            # Build throwaway adapter map for this session with OAuth token context
            adapter_map = await self._build_adapter_map(
                names=connected_names,
                session_id=session_id
            )
            print(f"DEBUG: aget_tools adapter_map: {adapter_map}")
            if not adapter_map:
                return []

            # Create session-scoped client
            client = MultiServerMCPClient(adapter_map)

            raw_tools = await asyncio.wait_for(
                client.get_tools(), timeout=TOOL_FETCH_TIMEOUT
            )
            return patch_tools_schema(raw_tools)

        except asyncio.TimeoutError:
            logging.warning("Timed out fetching tools for session context")
            return []
        except Exception as e:
            logging.exception(f"Failed to get tools for context: {e}")
            return []


# Global instance
mcp = MCPServerManager()
