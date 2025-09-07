import json
import asyncio
import logging
import redis.asyncio as redis
from typing import Dict, List, Optional, Any, Tuple
from django.contrib.auth.models import User
from django.conf import settings
from .models import MCPServer
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from django.utils import timezone
from pydantic.v1 import BaseModel
from fastmcp.client.auth.oauth import FileTokenStorage
from fastmcp.client import Client as FastMCPClient
from fastmcp.client.auth import OAuth

class EmptyArgsSchema(BaseModel):
    """An empty schema for tools that have no parameters."""
    pass

def _safe_json_dumps(obj: Any) -> str:
    """Safely serialize an object to JSON, handling non-serializable types."""
    def json_serializer(obj):
        if callable(obj):
            return str(obj)
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        else:
            return str(obj)
    
    try:
        return json.dumps(obj, default=json_serializer)
    except Exception as e:
        logging.warning(f"Failed to serialize object to JSON: {e}")
        return "{}"

class MCPRedisManager:
    def __init__(self, redis_url: str = None):
        self.redis_client = redis.from_url(redis_url or getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0'))
        self.connection_ttl = 86400  # 24 hours TTL for connections
    
    async def _get_redis_key_prefix(self, user: Optional[User] = None, session_key: Optional[str] = None) -> str:
        """Get the Redis key prefix for user or session."""
        print(f"[DEBUG] Redis manager - user: {user}, session_key: {session_key}")
        if user:
            return f"mcp:user:{user.id}"
        elif session_key:
            return f"mcp:session:{session_key}"
        else:
            raise ValueError("Either user or session_key must be provided")
    
    async def _get_server_keys(self, server_name: str, user: Optional[User] = None, session_key: Optional[str] = None) -> Dict[str, str]:
        """Get all Redis keys for a server connection."""
        prefix = await self._get_redis_key_prefix(user, session_key)
        return {
            "status": f"{prefix}:server:{server_name}:status",
            "tools": f"{prefix}:server:{server_name}:tools",
            "connected_at": f"{prefix}:server:{server_name}:connected_at",
            "connections": f"{prefix}:connections"
        }
    
    async def get_connection_status(self, server_name: str, user: Optional[User] = None, session_key: Optional[str] = None) -> str:
        """Get connection status for a server."""
        keys = await self._get_server_keys(server_name, user, session_key)
        status = await self.redis_client.get(keys["status"])
        return status.decode() if status else "DISCONNECTED"
    
    async def get_connection_tools(self, server_name: str, user: Optional[User] = None, session_key: Optional[str] = None) -> List[Dict]:
        """Get tools for a server connection."""
        keys = await self._get_server_keys(server_name, user, session_key)
        tools_json = await self.redis_client.get(keys["tools"])
        if tools_json:
            try:
                return json.loads(tools_json.decode())
            except json.JSONDecodeError:
                return []
        return []
    
    async def set_connection_status(self, server_name: str, status: str, tools: List[Dict] = None, user: Optional[User] = None, session_key: Optional[str] = None):
        """Set connection status and tools for a server."""
        keys = await self._get_server_keys(server_name, user, session_key)
        
        # Set status
        await self.redis_client.set(keys["status"], status, ex=self.connection_ttl)
        
        # Set tools if provided
        if tools is not None:
            tools_json = _safe_json_dumps(tools)
            await self.redis_client.set(keys["tools"], tools_json, ex=self.connection_ttl)
        
        # Update connections set
        if status == "CONNECTED":
            await self.redis_client.sadd(keys["connections"], server_name)
            await self.redis_client.set(keys["connected_at"], timezone.now().isoformat(), ex=self.connection_ttl)
        else:
            await self.redis_client.srem(keys["connections"], server_name)
            await self.redis_client.delete(keys["connected_at"])
    
    async def get_user_connections(self, user: Optional[User] = None, session_key: Optional[str] = None) -> List[str]:
        """Get list of connected server names for user/session."""
        prefix = await self._get_redis_key_prefix(user, session_key)
        connections_key = f"{prefix}:connections"
        connections = await self.redis_client.smembers(connections_key)
        return [conn.decode() for conn in connections]
    
    async def disconnect_all_servers(self, user: Optional[User] = None, session_key: Optional[str] = None):
        """Disconnect all servers for a user/session."""
        prefix = await self._get_redis_key_prefix(user, session_key)
        connections_key = f"{prefix}:connections"
        
        # Get all connected servers
        connections = await self.redis_client.smembers(connections_key)
        
        # Disconnect each server
        for server_name in connections:
            await self.set_connection_status(server_name.decode(), "DISCONNECTED", user=user, session_key=session_key)
    
    async def cleanup_expired_connections(self):
        """Clean up expired connections (called periodically)."""
        # Redis TTL handles this automatically, but you could add custom cleanup logic here
        pass

# Global instance
mcp_redis = MCPRedisManager()
