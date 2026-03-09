"""
MCP Server Manager - Core business logic for MCP server operations.

Handles server lifecycle, connection management, tool retrieval,
and session-isolated server interactions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple

from langchain_mcp_adapters.client import MultiServerMCPClient
from django.contrib.auth import get_user_model

User = get_user_model()
from fastmcp.client import Client as FastMCPClient
from fastmcp.client.auth.oauth import FileTokenStorage

from .models import MCPServer, Category
from .redis_manager import mcp_redis
from .oauth_storage import ClientTokenStorage, SimpleTokenAuth
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
        id: Optional[str] = None,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[dict] = None,
        headers: Optional[dict] = None,
        query_params: Optional[dict] = None,
        requires_oauth2: Optional[bool] = False,
        is_public: Optional[bool] = False,
        description: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
    ) -> MCPServer:
        """
        Update an existing MCP server by ID or create a new one.
        """

        server_data = {
            "name": name,
            "owner": owner,
            "transport": transport,
            "url": url,
            "command": command,
            "args": args or {},
            "headers": headers or {},
            "query_params": query_params or {},
            "enabled": True,
            "requires_oauth2": requires_oauth2,
            "is_public": is_public,
            "description": description,
        }
        # If ID is provided, update existing server by ID
        if id:
            try:
                rec = await MCPServer.objects.aget(pk=id)
                # Apply all attributes to the existing record
                for key, value in server_data.items():
                    setattr(rec, key, value)
                await rec.asave()
            except MCPServer.DoesNotExist:
                raise ValueError(f"Server with ID '{id}' does not exist")
        else:
            rec = await MCPServer.objects.acreate(**server_data)

        # Handle categories assignment (ManyToMany field must be set after save)
        if category_ids is not None:
            # Validate all category IDs exist
            categories = []
            for cat_id in category_ids:
                try:
                    category = await Category.objects.aget(pk=cat_id)
                    categories.append(category)
                except Category.DoesNotExist:
                    raise ValueError(f"Category with ID '{cat_id}' does not exist")

            # aset() handles everything: adds new, removes old, clears if empty list
            await rec.categories.aset(categories)

            if categories:
                category_names = [cat.name for cat in categories]
                logging.info(f"Server '{name}' saved with categories: {', '.join(category_names)}")
            else:
                logging.info(f"Cleared all categories for server '{name}'")

        await self.initialize_client()  # Refresh global client if needed
        return rec

    async def aremove_server(
        self,
        user: User,
        id: Optional[str] = None,
        name: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Remove an MCP server by ID (preferred) or by name and clean up OAuth tokens.

        Args:
            user: User who owns the server
            id: Server ID (preferred)
            name: Server name (fallback for backward compatibility)
            session_id: Session identifier

        Returns:
            True if server was deleted, False otherwise
        """
        try:
            if id:
                rec = await MCPServer.objects.filter(pk=id, owner=user).afirst()
            elif name:
                rec = await MCPServer.objects.filter(name=name, owner=user).afirst()
            else:
                return False

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
                    storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear tokens for {rec.name}: {e}")

            await rec.adelete()

            # Clear from server configs
            self.server_configs.pop(rec.name, None)

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

        For OAuth servers, this uses SimpleTokenAuth which loads existing tokens
        from storage without setting up callback handlers. The OAuth flow itself
        is handled separately via the API endpoint approach.

        Args:
            server: MCPServer instance
            session_id: Session identifier

        Returns:
            List of tool objects
        """
        if server.requires_oauth2:
            # Use SimpleTokenAuth to load existing tokens without callback handlers
            # The OAuth flow is handled via API endpoint (oauth_helper.py)
            auth = SimpleTokenAuth(
                server_url=server.url,
                user_id=None,  # Could extract from server.owner if needed
                session_id=session_id,
            )
            async with FastMCPClient(server.url, auth=auth) as client:
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
            qs = MCPServer.objects.filter(enabled=True)

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
