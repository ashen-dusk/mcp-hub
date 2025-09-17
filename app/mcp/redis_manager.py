import json
import asyncio
import logging
import redis.asyncio as redis
from typing import Dict, List, Optional, Any, Tuple
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
        redis_url = redis_url or getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        
        # For Redis Cloud, try different connection methods
        if 'redis-cloud.com' in redis_url:
            try:
                # Method 1: Try with SSL disabled
                from urllib.parse import urlparse
                parsed = urlparse(redis_url)
                self.redis_client = redis.Redis(
                    host=parsed.hostname,
                    port=parsed.port,
                    password=parsed.password,
                    decode_responses=True,
                    ssl=False
                )
                print(f"[DEBUG] Redis Cloud connection created (SSL disabled)")
            except Exception as e:
                print(f"[DEBUG] Redis Cloud connection failed: {e}")
                # Method 2: Try standard URL
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                print(f"[DEBUG] Redis Cloud connection created (standard URL)")
        else:
            # For local Redis
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            print(f"[DEBUG] Local Redis connection created")
        
        self.connection_ttl = 86400  # 24 hours TTL for connections
    
    async def _get_redis_key_prefix(self, session_id: str) -> str:
        """Get the Redis key prefix for a session."""
        if not session_id:
            raise ValueError("session_id is required")
        return f"mcp:session:{session_id}"
    
    async def _get_server_keys(self, server_name: str, session_id: str) -> Dict[str, str]:
        """Get all Redis keys for a server connection."""
        prefix = await self._get_redis_key_prefix(session_id)
        return {
            "status": f"{prefix}:server:{server_name}:status",
            "tools": f"{prefix}:server:{server_name}:tools",
            "connected_at": f"{prefix}:server:{server_name}:connected_at",
            "connections": f"{prefix}:connections"
        }
    
    async def get_connection_status(self, server_name: str, session_id: str) -> str:
        """Get connection status for a server."""
        keys = await self._get_server_keys(server_name, session_id)
        status = await self.redis_client.get(keys["status"])
        return status if status else "DISCONNECTED"
    
    async def get_connection_tools(self, server_name: str, session_id: str) -> List[Dict]:
        """Get tools for a server connection."""
        keys = await self._get_server_keys(server_name, session_id)
        tools_json = await self.redis_client.get(keys["tools"])
        if tools_json:
            try:
                return json.loads(tools_json)
            except json.JSONDecodeError:
                return []
        return []
    
    async def set_connection_status(self, server_name: str, status: str, tools: List[Dict] = None, session_id: str = ""):
        """Set connection status and tools for a server."""
        keys = await self._get_server_keys(server_name, session_id)
        
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
    
    async def get_user_connections(self, session_id: str) -> List[str]:
        """Get list of connected server names for session."""
        prefix = await self._get_redis_key_prefix(session_id)
        connections_key = f"{prefix}:connections"
        connections = await self.redis_client.smembers(connections_key)
        return list(connections) if connections else []
    
    async def disconnect_all_servers(self, session_id: str):
        """Disconnect all servers for a session."""
        prefix = await self._get_redis_key_prefix(session_id)
        connections_key = f"{prefix}:connections"
        
        # Get all connected servers
        connections = await self.redis_client.smembers(connections_key)
        
        # Disconnect each server
        for server_name in connections:
            await self.set_connection_status(server_name, "DISCONNECTED", session_id=session_id)
    
    async def cleanup_expired_connections(self):
        """Clean up expired connections (called periodically)."""
        # Redis TTL handles this automatically, but you could add custom cleanup logic here
        pass

# Global instance
mcp_redis = MCPRedisManager()
