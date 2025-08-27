import json
import asyncio
import logging
import ast
from typing import Dict, List, Optional, Any, Tuple
from langchain_mcp_adapters.client import MultiServerMCPClient
from .models import MCPServer
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from django.utils import timezone
from pydantic.v1 import BaseModel
from fastmcp.client.auth.oauth import FileTokenStorage

# OAuth2Error removed since we're using FastMCP's built-in OAuth
try:
    from fastmcp.client import Client as FastMCPClient  # type: ignore
    from fastmcp.client.auth import OAuth  # type: ignore
except Exception:  # pragma: no cover
    FastMCPClient = None  # type: ignore
    OAuth = None  # type: ignore

class EmptyArgsSchema(BaseModel):
    """An empty schema for tools that have no parameters."""
    pass

def _safe_json_loads(s: Optional[str]) -> Optional[Any]:
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError, MemoryError):
            logging.warning(f"Could not parse JSON/literal string: {s}")
            return None


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

# ── mcp: manager ─────────────────────────────────────────────────────────────
class MCP:
    def __init__(self):
        self.client: Optional[MultiServerMCPClient] = None
        self.adapter_map: Dict[str, Dict[str, Any]] = {}
        self.tools: List[Any] = []
        self.connections: Dict[str, Dict[str, Any]] = {}  # Track connected servers and their tools
    
    def _patch_tools_schema(self, tools: List[Any]) -> List[Any]:
        """Ensures all tools have a valid schema for OpenAI."""
        for tool in tools:
            # FIX: OpenAI requires a non-empty object for function parameters.
            # A schema is invalid if it's missing, or if it's a dict
            # without a 'properties' key.
            args_schema = getattr(tool, "args_schema", None)
            is_invalid_dict_schema = isinstance(args_schema, dict) and "properties" not in args_schema

            if not args_schema or is_invalid_dict_schema:
                tool.args_schema = EmptyArgsSchema
        return tools

    def _serialize_tools(self, tools: List[Any]) -> List[Dict[str, Any]]:
        """Convert tool objects to a serializable list of dicts for GraphQL."""
        tools_info: List[Dict[str, Any]] = []
        for tool in tools:
            schema_dict = {}

            # A tool's schema should be on the `args_schema` attribute.
            if hasattr(tool, "args_schema"):
                args_schema = tool.args_schema
                # Case 1: It's a Pydantic model, so we call .schema() to generate the dict.
                if hasattr(args_schema, "schema") and callable(args_schema.schema):
                    try:
                        schema_dict = args_schema.schema()
                    except Exception:
                        pass
                # Case 2: It's already a dictionary.
                elif isinstance(args_schema, dict):
                    schema_dict = args_schema

            tool_info = {
                "name": getattr(tool, 'name', str(tool)),
                "description": getattr(tool, 'description', ''),
                "schema": _safe_json_dumps(schema_dict) if schema_dict else "{}",
            }
            tools_info.append(tool_info)
        return tools_info

    async def alist_servers(self) -> List[MCPServer]:
        """Get all servers with connection status and tool information."""
        servers = [s async for s in MCPServer.objects.all().order_by("name")]
        
        # add connection status and tool info to each server
        for server in servers:
            # :: if server is live, get tools from the live connection
            if server.name in self.connections:
                connected_info = self.connections[server.name]
                server.tools = self._serialize_tools(connected_info["tools"])
            # :: otherwise, get tools from the last known state in the DB
            elif server.tools:
                server.tools = server.tools
            else:
                server.tools = []
        
        return servers

    async def areset_all_server_statuses(self):
        """Sets all servers to DISCONNECTED on application startup."""
        await MCPServer.objects.all().aupdate(
            connection_status="DISCONNECTED",
            tools=[]
        )

    async def asave_server(
        self,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[dict] = None,
        headers: Optional[dict] = None,
        query_params: Optional[dict] = None,
    ) -> MCPServer:
        rec, _ = await MCPServer.objects.aupdate_or_create(
            name=name,
            defaults={
                "transport": transport,
                "url": url,
                "command": command,
                "args": args or {},
                "headers": headers or {},
                "query_params": query_params or {},
                "enabled": True,
            },
        )
        await self.initialize_client()  # re-initialize on change
        return rec

    async def aremove_server(self, name: str) -> bool:
        try:
            rec = await MCPServer.objects.aget(name=name)
            if rec.url:
                try:
                    storage = FileTokenStorage(server_url=rec.url)
                    await storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear tokens for {name}: {e}")

            await rec.adelete()
            # Ensure any live connection tracking is cleared
            if name in self.connections:
                try:
                    del self.connections[name]
                except Exception:
                    pass
            await self.initialize_client()  # re-initialize on change
            return True
        except MCPServer.DoesNotExist:
            return False

    async def aet_server_enabled(self, name: str, enabled: bool) -> MCPServer:
        try:
            rec = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            raise ValueError(f"MCPServer with name '{name}' not found.")

        rec.enabled = enabled
        await rec.asave(update_fields=["enabled", "updated_at"])
        # If disabling, clear connection tracking for this server
        if not enabled and name in self.connections:
            try:
                del self.connections[name]
            except Exception:
                pass
        await self.initialize_client()  # re-initialize on change
        return rec

    async def _build_adapter_map(self, names: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        adapter_map: Dict[str, Dict[str, Any]] = {}
        # Only build configs for explicitly provided names (connected servers)
        if not names:
            return adapter_map
        qs = MCPServer.objects.filter(enabled=True, name__in=list(names))
        async for rec in qs.all():
            logging.debug(f"Building adapter map for: name={rec.name} transport={rec.transport}")
            if rec.transport == "stdio":
                adapter_map[rec.name] = {
                    "command": rec.command or "",
                    "args": [str(x) for x in rec.args if isinstance(rec.args, list)],
                    "transport": "stdio",
                }
            else:
                base_url = rec.url or ""
                if rec.query_params:
                    logging.debug(f"Merging query params for {rec.name}: {rec.query_params}")
                    qp = rec.query_params
                    if isinstance(qp, dict) and qp:
                        try:
                            parts = list(urlsplit(base_url))
                            existing = dict(
                                parse_qsl(parts[3], keep_blank_values=True)
                            )
                            merged = {**existing, **{k: v for k, v in qp.items()}}
                            parts[3] = urlencode(merged, doseq=True)
                            base_url = urlunsplit(parts)
                            logging.debug(f"Final base_url for {rec.name}: {base_url}")
                        except Exception as e:
                            logging.warning(f"Error merging query params for {rec.name}: {e}")

                entry: Dict[str, Any] = {
                    "url": base_url,
                    "transport": rec.transport,
                }
                # Attach headers only from DB, no extra auth management
                if rec.headers and isinstance(rec.headers, dict) and rec.headers:
                    entry["headers"] = rec.headers
                
                adapter_map[rec.name] = entry
        return adapter_map

    async def initialize_client(self):
        # Restrict adapter map to only explicitly connected servers
        connected_names = list(self.connections.keys())
        self.adapter_map = await self._build_adapter_map(names=connected_names)
        if not self.adapter_map:
            self.client = None
            self.tools = []
            return

        try:
            logging.debug(f"Initializing MCP client with adapter map: {self.adapter_map}")
            self.client = MultiServerMCPClient(self.adapter_map)
            raw_tools = await asyncio.wait_for(self.client.get_tools(), timeout=8.0)
            self.tools = self._patch_tools_schema(raw_tools)

        except asyncio.TimeoutError:
            logging.warning("MCP client initialization or tool fetching timed out.")
            self.client = None
            self.tools = []
        except Exception as e:
            logging.exception(f"Failed to initialize MCP client: {e}")
            # try to handle specific transport errors
            if "SSEError" in str(e) or "text/event-stream" in str(e):
                logging.warning("SSE transport error detected, this might be a server configuration issue")
            self.client = None
            self.tools = []

    # .. op: acheck_server_health
    async def acheck_server_health(self, name: str) -> tuple[str, list[dict[str, Any]]]:
        """
        Check server health and return tools if healthy.
        
        Returns:
            Tuple of (status: str, tools: List[Dict])
        """
        try:
            server = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            return "NOT_FOUND", []

        if not server.enabled:
            return "DISABLED", []

        try:
            adapter_map = await self._build_adapter_map(names=[name])
            if name not in adapter_map:
                return "ERROR", []
            raw_tools = await asyncio.wait_for(self.client.get_tools(), timeout=5.0)
            tools = self._patch_tools_schema(raw_tools)
            # Convert tools to serializable format
            tools_info = self._serialize_tools(tools)

            return "OK", tools_info
        except asyncio.TimeoutError:
            return "TIMEOUT", []
        except Exception as e:
            logging.warning(f"Health check for {name} failed: {e}")
            return "ERROR", []  

    # .. op: connect_server
    async def connect_server(self, name: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
        """
        Connect to a specific MCP server using FastMCP's client and return tools.
        This uses the documented auth="oauth" pattern and returns tools for the frontend.
        """
        try:
            server = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            return False, "Server not found", []

        if not server.enabled:
            return False, "Server is disabled", []

        if not server.url:
            return False, "Server URL is not configured", []

        if FastMCPClient is None or OAuth is None:
            return False, "FastMCP client is not available", []

        try:
            # Use FastMCP client with explicit scopes to match server grants ( works with scalekit.ai)
            oauth = OAuth(
                mcp_url=server.url,
                client_name="Inspect MCP",
                callback_port=8293,
                # scopes=["openid", "email", "profile", "search:read", "trends:read", "transcripts:read", "analytics:read"],
            )
            async with FastMCPClient(server.url, auth=oauth) as client:  # type: ignore
                await asyncio.wait_for(client.ping(), timeout=15.0)
                tools_objs = await asyncio.wait_for(client.list_tools(), timeout=15.0)

            # Convert tools for storage/GraphQL
            tools_info: List[Dict[str, Any]] = []
            for t in tools_objs:
                tools_info.append({
                    "name": getattr(t, "name", str(t)),
                    "description": getattr(t, "description", ""),
                    "schema": "{}",
                })

            # Track connection state (no persistent client needed for now)
            self.connections[name] = {
                "client": None,
                "config": {"url": server.url},
                "tools": tools_objs,
            }

            # Persist tools for frontend consumption
            server.connection_status = "CONNECTED"
            server.tools = tools_info
            await server.asave(update_fields=["connection_status", "tools", "updated_at"])

            return True, "Connected successfully (OAuth)", tools_info

        except asyncio.TimeoutError:
            # Timeout while pinging or listing tools
            try:
                server.connection_status = "FAILED"
                server.tools = []
                await server.asave(update_fields=["connection_status", "tools", "updated_at"])
            except Exception:
                pass
            return False, "Connection timeout", []
        except Exception as e:
            # Update state and report the error message
            try:
                server.connection_status = "FAILED"
                server.tools = []
                await server.asave(update_fields=["connection_status", "tools", "updated_at"])
            except Exception:
                pass
            return False, f"Connection failed: {str(e)}", []

    # .. op: disconnect_server
    async def disconnect_server(self, name: str) -> Tuple[bool, str]:
        """
        Disconnect from a specific MCP server.
        
        Returns:
            Tuple of (success: bool, status_message: str)
        """
        try:
            if name not in self.connections:
                return False, "Server not connected"
            
            # get the client and close it if it has a close method
            server_info = self.connections[name]
            client = server_info.get("client")
            # print(f"Client: {client}")
            print(f"Client type: {dir(client)}")
            if hasattr(client, 'close'):
                try:
                    logging.info(f"Closing client for {name}")
                    print(f"Closing client for {name}")
                    await client.close()
                except Exception as e:
                    logging.warning(f"Error closing client for {name}: {e}")
       
            # remove from adapter map if present (runtime disconnect)
            if name in self.adapter_map:
                try:
                    del self.adapter_map[name]
                except Exception:
                    pass

            # always remove from connected tracking and rebuild client
            try:
                del self.connections[name]
            except Exception:
                pass

            await self.initialize_client()

            # :: update server status in the database
            try:
                server = await MCPServer.objects.aget(name=name)
                server.connection_status = "DISCONNECTED"
                server.tools = []
                await server.asave(update_fields=["connection_status", "tools", "updated_at"])
            except MCPServer.DoesNotExist:
                pass  # Or log a warning

            return True, "Disconnected successfully"
            
        except Exception as e:
            logging.exception(f"Failed to disconnect from server {name}: {e}")
            return False, f"Disconnect failed: {str(e)}"

    def get_client(self) -> Optional[MultiServerMCPClient]:
        return self.client

    def get_tools(self) -> List[Any]:
        return self.tools


# global instance
mcp = MCP()


