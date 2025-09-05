import json
import asyncio
import logging
import ast
from typing import Dict, List, Optional, Any, Tuple
from langchain_mcp_adapters.client import MultiServerMCPClient
from django.contrib.auth.models import User
from .models import MCPServer
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from django.utils import timezone
from pydantic.v1 import BaseModel
from fastmcp.client.auth.oauth import FileTokenStorage

# OAuth2Error removed since we're using FastMCP's built-in OAuth

from fastmcp.client import Client as FastMCPClient  # type: ignore
from fastmcp.client.auth import OAuth  # type: ignore

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
            
            # Handle FastMCP tools (from connect_server)
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                schema_dict = tool.inputSchema
            elif hasattr(tool, "input_schema") and tool.input_schema:
                schema_dict = tool.input_schema
            # Handle LangChain MCP tools (from old client)
            elif hasattr(tool, "args_schema"):
                args_schema = tool.args_schema
                if hasattr(args_schema, "schema") and callable(args_schema.schema):
                    try:
                        schema_dict = args_schema.schema()
                    except Exception:
                        pass
                elif isinstance(args_schema, dict):
                    schema_dict = args_schema

            tool_info = {
                "name": getattr(tool, 'name', str(tool)),
                "description": getattr(tool, 'description', '') or '',
                "schema": _safe_json_dumps(schema_dict) if schema_dict else "{}",
            }
            tools_info.append(tool_info)
        return tools_info

    async def alist_servers(self) -> List[MCPServer]:
        """Get all servers with connection status and tool information."""
        servers = [s async for s in MCPServer.objects.filter(is_public=True).order_by("name")]
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
        owner: User,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[dict] = None,
        headers: Optional[dict] = None,
        query_params: Optional[dict] = None,
        requires_oauth2: Optional[bool] = False,
        is_public: Optional[bool] = False,
    ) -> MCPServer:
        rec, _ = await MCPServer.objects.aupdate_or_create(
            name=name,
            owner=owner,
            is_public=is_public,
            defaults={
                "transport": transport,
                "url": url,
                "command": command,
                "args": args or {},
                "headers": headers or {},
                "query_params": query_params or {},
                "enabled": True,
                "requires_oauth2": requires_oauth2,
            },
        )
        await self.initialize_client()  # re-initialize on change
        return rec

    async def aremove_server(self, name: str, user: User) -> bool:
        try:
            rec = await MCPServer.objects.filter(
                    name=name,
                    owner=user 
            ).afirst()
           
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
                # Attach headers from DB
                if rec.headers and isinstance(rec.headers, dict) and rec.headers:
                    entry["headers"] = rec.headers
                
                # Conditionally add OAuth2 tokens if required
                if rec.requires_oauth2:
                    try:
                        storage = FileTokenStorage(server_url=rec.url)
                        print(f"Storage: {storage}")
                        tokens = await storage.get_tokens()
                        print(f"Token data: {tokens}")
                        if tokens and tokens.access_token:
                            # Merge with existing headers or create new headers dict
                            if "headers" not in entry:
                                entry["headers"] = {}
                            entry["headers"]["Authorization"] = f"Bearer {tokens.access_token}"
                    except Exception as e:
                        logging.warning(f"Failed to fetch OAuth token for {rec.name}: {e}")
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
            raw_tools = await asyncio.wait_for(self.client.get_tools(), timeout=30)
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

    # .. op: arestart_mcp_server
    async def arestart_mcp_server(self, name: str) -> tuple[str, list[dict[str, Any]]]:
        """
        Check server health and return tools if healthy.
        
        Returns:
            Tuple of (status: str, tools: List[Dict])
        """
        try:
            server = await MCPServer.objects.aget(name=name)
            if server.url:
                try:
                    storage = FileTokenStorage(server_url=server.url)
                    await storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear tokens for {name}: {e}")
        except MCPServer.DoesNotExist:
            return "NOT_FOUND", []

        if not server.enabled:
            return "DISABLED", []
         
        try:
            adapter_map = await self._build_adapter_map(names=[name])
            if name not in adapter_map:
                return "ERROR", []
            
            tools_info = []
            if server.requires_oauth2:
               async with FastMCPClient(server.url, auth=OAuth(mcp_url=server.url, client_name="Inspect MCP", callback_port=8293, scopes=[],)) as client:
                  await client.ping()
                  raw_tools = await client.list_tools()
                  tools = self._patch_tools_schema(raw_tools)
                  tools_info = self._serialize_tools(tools)
            else:
                async with FastMCPClient(server.url) as client:
                    await client.ping()
                    raw_tools = await client.list_tools()
                    tools = self._patch_tools_schema(raw_tools)
                    tools_info = self._serialize_tools(tools)
            self.connections[name] = {
                "client": None,
                "config": {"url": server.url},
                "tools": tools,
            }
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
        Conditionally uses OAuth2 authentication based on the requires_oauth2 field.
        """
        try:
            server = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            return False, "Server not found", []

        # if not server.enabled:
        #     return False, "Server is disabled", []

        if not server.url:
            return False, "Server URL is not configured", []

        if FastMCPClient is None:
            return False, "FastMCP client is not available", []

        try:
            # Check if OAuth2 is required for this server
            if server.requires_oauth2:
                oauth = OAuth(
                    mcp_url=server.url,
                    client_name="Inspect MCP",
                    callback_port=8293,
                    scopes=[],
                    # scopes=["openid", "email", "profile"],
                )
                print(f"OAuth: {oauth}")
                async with FastMCPClient(server.url, auth=oauth) as client:  # type: ignore
                    await asyncio.wait_for(client.ping(), timeout=30.0)
                    tools_objs = await asyncio.wait_for(client.list_tools(), timeout=30.0)
                    print(f"Tools objs: {tools_objs}")
            else:
                # Use FastMCP client without authentication
                async with FastMCPClient(server.url) as client:  # type: ignore
                    await asyncio.wait_for(client.ping(), timeout=30.0)
                    tools_objs = await asyncio.wait_for(client.list_tools(), timeout=30.0)
                    print(f"Tools objs: {tools_objs}")

            # convert tools for storage/GraphQL
            tools = self._patch_tools_schema(tools_objs)
            tools_info = self._serialize_tools(tools)
            # Track connection state (no persistent client needed for now)
            self.connections[name] = {
                "client": None,
                "config": {"url": server.url},
                "tools": tools_objs,
            }

            # Persist tools for frontend consumption
            success_message = "Connected successfully"
            server.connection_status = "CONNECTED"
            server.tools = tools_info
            
            await server.asave(update_fields=["connection_status", "tools", "updated_at"])

            return True, success_message, tools_info

        except asyncio.TimeoutError:
            # Timeout while pinging or listing tools
            try:
                print(f"Connection timeout", e)
                server.connection_status = "FAILED"
                server.tools = []
                await server.asave(update_fields=["connection_status", "tools", "updated_at"])
            except Exception:
                pass
            return False, "Connection timeout", []
        except Exception as e:
            # Update state and report the error message
            try:
                print(f"Connection failed: {str(e)}")
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


