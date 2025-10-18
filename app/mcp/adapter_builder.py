"""
MCP Adapter Builder - Constructs adapter configurations for LangChain MultiServerMCPClient.

This module is responsible for building adapter maps from MCPServer configurations,
handling URL construction, query parameters, headers, and OAuth2 token injection.
"""

import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from .oauth_storage import ClientTokenStorage
from .models import MCPServer


class MCPAdapterBuilder:
    """
    Builds adapter configurations for LangChain MultiServerMCPClient.

    Responsibilities:
    - Convert MCPServer DB records to adapter config format
    - Handle different transport types (stdio, SSE, WebSocket)
    - Merge query parameters and headers
    - Inject OAuth2 tokens when required

    This class is stateless and thread-safe - all methods are pure
    transformations based on input data.
    """

    def __init__(self):
        """Initialize the adapter builder."""
        pass

    async def build_adapter_map(
        self,
        server_names: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build adapter configuration map for specified servers.

        This is the main entry point that orchestrates the building process.

        Args:
            server_names: List of server names to include (None = empty map)
            session_id: Session identifier for OAuth token isolation
            user_id: User identifier for OAuth token isolation

        Returns:
            Dictionary mapping server names to adapter configs:
            {
                "server1": {
                    "url": "https://api.example.com",
                    "transport": "sse",
                    "headers": {"Authorization": "Bearer token..."}
                },
                "server2": {
                    "command": "python",
                    "args": ["server.py"],
                    "transport": "stdio"
                }
            }
        """
        adapter_map: Dict[str, Dict[str, Any]] = {}

        if not server_names:
            return adapter_map

        # Fetch enabled servers matching the requested names
        qs = MCPServer.objects.filter(enabled=True, name__in=list(server_names))

        async for server in qs.all():
            logging.debug(
                f"Building adapter for: name={server.name} transport={server.transport}"
            )

            adapter_config = await self._build_server_adapter(server, session_id, user_id)
            adapter_map[server.name] = adapter_config

        return adapter_map

    async def _build_server_adapter(
        self,
        server: MCPServer,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build adapter configuration for a single server.

        Routes to appropriate builder based on transport type.

        Args:
            server: MCPServer instance
            session_id: Session identifier for OAuth token isolation
            user_id: User identifier for OAuth token isolation

        Returns:
            Adapter configuration dictionary
        """
        if server.transport == "stdio":
            return self._build_stdio_adapter(server)
        else:
            return await self._build_network_adapter(server, session_id, user_id)

    def _build_stdio_adapter(self, server: MCPServer) -> Dict[str, Any]:
        """
        Build adapter configuration for stdio transport.

        Args:
            server: MCPServer instance

        Returns:
            Stdio adapter configuration
        """
        return {
            "command": server.command or "",
            "args": [
                str(x) for x in server.args
                if isinstance(server.args, list)
            ],
            "transport": "stdio",
        }

    async def _build_network_adapter(
        self,
        server: MCPServer,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build adapter configuration for network transports (SSE, WebSocket, etc.).

        Args:
            server: MCPServer instance
            session_id: Session identifier for OAuth token isolation
            user_id: User identifier for OAuth token isolation

        Returns:
            Network adapter configuration
        """
        # Build URL with query parameters
        url = self.build_server_url(server)

        entry: Dict[str, Any] = {
            "url": url,
            "transport": server.transport,
        }

        # Attach headers from DB
        if server.headers and isinstance(server.headers, dict) and server.headers:
            entry["headers"] = dict(server.headers)  # Create a copy

        # Add OAuth2 tokens if required
        if server.requires_oauth2:
            entry = await self.add_oauth_headers(entry, server, session_id, user_id)

        return entry

    def build_server_url(self, server: MCPServer) -> str:
        """
        Build complete server URL with merged query parameters.

        Merges query parameters from the server configuration with any
        existing parameters in the URL.

        Args:
            server: MCPServer instance

        Returns:
            Complete URL string with merged query parameters

        Example:
            Input: url="https://api.example.com?foo=1", query_params={"bar": "2"}
            Output: "https://api.example.com?foo=1&bar=2"
        """
        base_url = server.url or ""

        if not server.query_params:
            return base_url

        qp = server.query_params

        if not isinstance(qp, dict) or not qp:
            return base_url

        try:
            logging.debug(f"Merging query params for {server.name}: {qp}")

            # Parse URL into components
            parts = list(urlsplit(base_url))

            # Get existing query parameters
            existing = dict(parse_qsl(parts[3], keep_blank_values=True))

            # Merge with new parameters (new ones take precedence)
            merged = {**existing, **{k: v for k, v in qp.items()}}

            # Rebuild query string
            parts[3] = urlencode(merged, doseq=True)

            # Reassemble URL
            final_url = urlunsplit(parts)

            logging.debug(f"Final URL for {server.name}: {final_url}")
            return final_url

        except Exception as e:
            logging.warning(
                f"Error merging query params for {server.name}: {e}"
            )
            return base_url

    async def add_oauth_headers(
        self,
        entry: Dict[str, Any],
        server: MCPServer,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add OAuth2 authorization headers to adapter entry.

        Fetches OAuth tokens from user/session-isolated storage and adds Authorization header.
        Creates headers dict if it doesn't exist.

        Args:
            entry: Adapter configuration dictionary
            server: MCPServer instance
            session_id: Session identifier for OAuth token isolation
            user_id: User identifier for OAuth token isolation

        Returns:
            Updated adapter configuration with OAuth headers
        """
        try:
            # Use ClientTokenStorage to access session-isolated tokens
            storage = ClientTokenStorage(
                server_url=server.url,
                user_id=user_id,
                session_id=session_id
            )
            tokens = await storage.get_tokens()

            if tokens and tokens.access_token:
                # Ensure headers dict exists
                if "headers" not in entry:
                    entry["headers"] = {}

                # Add authorization header
                entry["headers"]["Authorization"] = f"Bearer {tokens.access_token}"

                logging.info(f"Added OAuth token for {server.name} (session: {session_id or user_id})")

        except Exception as e:
            logging.warning(f"Failed to fetch OAuth token for {server.name}: {e}")

        return entry

    def validate_adapter_map(self, adapter_map: Dict[str, Dict[str, Any]]) -> bool:
        """
        Validate an adapter map configuration.

        Useful for testing and debugging adapter configurations.

        Args:
            adapter_map: Adapter configuration to validate

        Returns:
            True if valid, False otherwise
        """
        for name, config in adapter_map.items():
            # Check required fields
            if "transport" not in config:
                logging.error(f"Server {name} missing 'transport' field")
                return False

            transport = config["transport"]

            # Validate stdio config
            if transport == "stdio":
                if "command" not in config:
                    logging.error(f"Stdio server {name} missing 'command' field")
                    return False

            # Validate network config
            else:
                if "url" not in config:
                    logging.error(f"Network server {name} missing 'url' field")
                    return False

        return True
