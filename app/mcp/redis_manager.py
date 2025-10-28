"""
Redis manager for MCP connection state.

Handles all Redis operations for storing and retrieving MCP server
connection states, tools, and session-specific data.
"""

import json
import logging
from typing import Dict, List, Optional

import redis.asyncio as redis
from django.conf import settings
from django.utils import timezone

from .constants import REDIS_CONNECTION_TTL, REDIS_KEY_PREFIX
from .utils import safe_json_dumps


class MCPRedisManager:
    """
    Manages Redis operations for MCP server connections.

    Provides session-isolated storage for connection states, tools,
    and metadata with automatic TTL-based cleanup.
    """

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis manager.

        Args:
            redis_url: Redis connection URL (defaults to settings.REDIS_URL)
        """
        redis_url = redis_url or getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        self.redis_client = self._create_redis_client(redis_url)
        self.connection_ttl = REDIS_CONNECTION_TTL

    def _create_redis_client(self, redis_url: str) -> redis.Redis:
        """
        Create Redis client with appropriate connection settings.

        Args:
            redis_url: Redis connection URL

        Returns:
            Configured Redis client instance
        """
        # Connection pool settings to prevent "max number of clients reached"
        # Redis Cloud Free Tier limit: ~30 connections
        # Setting to 20 to leave headroom for other operations
        connection_pool_kwargs = {
            'decode_responses': True,
            'max_connections': 20,  # Limit for Redis Cloud upto (30 total)
            'socket_keepalive': True,  # Enable TCP keepalive
            'socket_keepalive_options': {},  # Use default keepalive options
            'health_check_interval': 30,  # Health check every 30 seconds
        }

        # Handle Redis Cloud with SSL considerations
        if 'redis-cloud.com' in redis_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(redis_url)
                client = redis.Redis(
                    host=parsed.hostname,
                    port=parsed.port,
                    password=parsed.password,
                    ssl=False,
                    **connection_pool_kwargs
                )
                logging.info("Redis Cloud connection created (SSL disabled) with connection pool")
                return client
            except Exception as e:
                logging.warning(f"Redis Cloud SSL connection failed: {e}, trying standard URL")
                # Fallback to standard URL parsing

        # Standard Redis connection with connection pool
        client = redis.from_url(redis_url, **connection_pool_kwargs)
        logging.info("Redis connection created with connection pool (max_connections=20)")
        return client

    def _build_key(self, session_id: str, *parts: str) -> str:
        """
        Build a Redis key from session and parts.

        Args:
            session_id: Session identifier
            *parts: Additional key components

        Returns:
            Formatted Redis key
        """
        if not session_id:
            raise ValueError("session_id is required")

        key_parts = [REDIS_KEY_PREFIX, "session", session_id] + list(parts)
        return ":".join(key_parts)

    async def get_connection_status(self, server_name: str, session_id: str) -> str:
        """
        Get connection status for a server.

        Args:
            server_name: Name of the MCP server
            session_id: Session identifier

        Returns:
            Connection status string (CONNECTED/DISCONNECTED/FAILED)
        """
        key = self._build_key(session_id, "server", server_name, "status")
        status = await self.redis_client.get(key)
        return status if status else "DISCONNECTED"

    async def get_connection_tools(self, server_name: str, session_id: str) -> List[Dict]:
        """
        Get tools for a server connection.

        Args:
            server_name: Name of the MCP server
            session_id: Session identifier

        Returns:
            List of tool dictionaries
        """
        key = self._build_key(session_id, "server", server_name, "tools")
        tools_json = await self.redis_client.get(key)

        if tools_json:
            try:
                return json.loads(tools_json)
            except json.JSONDecodeError as e:
                logging.warning(f"Failed to decode tools JSON for {server_name}: {e}")
                return []
        return []

    async def set_connection_status(
        self,
        server_name: str,
        status: str,
        tools: Optional[List[Dict]] = None,
        session_id: str = ""
    ) -> None:
        """
        Set connection status and tools for a server.

        Args:
            server_name: Name of the MCP server
            status: Connection status (CONNECTED/DISCONNECTED/FAILED)
            tools: Optional list of tool dictionaries
            session_id: Session identifier
        """
        status_key = self._build_key(session_id, "server", server_name, "status")
        tools_key = self._build_key(session_id, "server", server_name, "tools")
        connected_at_key = self._build_key(session_id, "server", server_name, "connected_at")
        connections_key = self._build_key(session_id, "connections")

        # Set status with TTL
        await self.redis_client.set(status_key, status, ex=self.connection_ttl)

        # Set tools if provided
        if tools is not None:
            tools_json = safe_json_dumps(tools)
            await self.redis_client.set(tools_key, tools_json, ex=self.connection_ttl)

        # Update connections set and metadata
        if status == "CONNECTED":
            await self.redis_client.sadd(connections_key, server_name)
            await self.redis_client.set(
                connected_at_key,
                timezone.now().isoformat(),
                ex=self.connection_ttl
            )
        else:
            # Remove from connections set on disconnect/failure
            await self.redis_client.srem(connections_key, server_name)
            await self.redis_client.delete(connected_at_key)

    async def get_connected_servers(self, session_id: str) -> List[str]:
        """
        Get list of connected server names for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of connected server names
        """
        connections_key = self._build_key(session_id, "connections")
        connections = await self.redis_client.smembers(connections_key)
        return list(connections) if connections else []

    async def disconnect_all_servers(self, session_id: str) -> None:
        """
        Disconnect all servers for a session.

        Args:
            session_id: Session identifier
        """
        # Get all connected servers
        connections = await self.get_connected_servers(session_id)

        # Disconnect each server
        for server_name in connections:
            await self.set_connection_status(
                server_name,
                "DISCONNECTED",
                session_id=session_id
            )

    async def clear_session_data(self, session_id: str) -> None:
        """
        Clear all Redis data for a specific session.

        Args:
            session_id: Session identifier
        """
        pattern = self._build_key(session_id, "*")

        # Find all keys matching the session pattern
        cursor = 0
        while True:
            cursor, keys = await self.redis_client.scan(
                cursor=cursor,
                match=pattern,
                count=100
            )

            if keys:
                await self.redis_client.delete(*keys)

            if cursor == 0:
                break

        logging.info(f"Cleared all data for session: {session_id}")

    async def health_check(self) -> bool:
        """
        Check if Redis connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            await self.redis_client.ping()
            return True
        except Exception as e:
            logging.error(f"Redis health check failed: {e}")
            return False

    async def close(self) -> None:
        """
        Close the Redis connection and clean up resources.
        Should be called when shutting down the application.
        """
        try:
            await self.redis_client.close()
            logging.info("Redis connection closed")
        except Exception as e:
            logging.error(f"Error closing Redis connection: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # OAuth Session Management
    # ──────────────────────────────────────────────────────────────────────

    def _build_oauth_session_key(self, state: str) -> str:
        """
        Build a Redis key for OAuth session data.

        Args:
            state: OAuth state parameter

        Returns:
            Formatted Redis key
        """
        return f"{REDIS_KEY_PREFIX}:oauth:session:{state}"

    async def store_oauth_session(
        self,
        state: str,
        server_name: str,
        session_id: str,
        user_id: Optional[str] = None,
        ttl: int = 600  # 10 minutes
    ) -> None:
        """
        Store OAuth session data in Redis.

        This data links the OAuth state parameter to the server connection context.

        Args:
            state: OAuth state parameter
            server_name: Name of the MCP server
            session_id: Session identifier
            user_id: Optional user identifier
            ttl: Time-to-live in seconds (default: 600 = 10 minutes)
        """
        key = self._build_oauth_session_key(state)
        data = {
            "state": state,
            "server_name": server_name,
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": timezone.now().isoformat()
        }
        await self.redis_client.set(key, safe_json_dumps(data), ex=ttl)
        logging.info(f"[OAuth Redis] Stored session for state: {state[:8]}..., server: {server_name}")

    async def get_oauth_session(self, state: str) -> Optional[Dict[str, str]]:
        """
        Retrieve OAuth session data from Redis.

        Args:
            state: OAuth state parameter

        Returns:
            Dictionary with session data if found, None otherwise
        """
        key = self._build_oauth_session_key(state)
        data_json = await self.redis_client.get(key)

        if data_json:
            try:
                data = json.loads(data_json)
                logging.info(f"[OAuth Redis] Retrieved session for state: {state[:8]}...")
                return data
            except json.JSONDecodeError as e:
                logging.error(f"[OAuth Redis] Failed to decode session data: {e}")
                return None

        logging.debug(f"[OAuth Redis] No session found for state: {state[:8]}...")
        return None

    async def delete_oauth_session(self, state: str) -> None:
        """
        Delete OAuth session data from Redis.

        Args:
            state: OAuth state parameter
        """
        key = self._build_oauth_session_key(state)
        await self.redis_client.delete(key)
        logging.info(f"[OAuth Redis] Deleted session for state: {state[:8]}...")


# Global instance
mcp_redis = MCPRedisManager()
