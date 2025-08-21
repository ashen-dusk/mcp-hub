import json
import asyncio
import logging
import ast
from typing import Dict, List, Optional, Any, Tuple
from langchain_mcp_adapters.client import MultiServerMCPClient
from .models import MCPServer
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl


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
        self.connected_servers: Dict[str, Dict[str, Any]] = {}  # Track connected servers and their tools
    
    def _serialize_tools(self, tools: List[Any]) -> List[Dict[str, Any]]:
        """Convert tool objects to a serializable list of dicts for GraphQL."""
        tools_info: List[Dict[str, Any]] = []
        for tool in tools:
            schema = getattr(tool, 'schema', {})
            tool_info = {
                "name": getattr(tool, 'name', str(tool)),
                "description": getattr(tool, 'description', ''),
                "schema": _safe_json_dumps(schema) if schema else "{}",
            }
            tools_info.append(tool_info)
        return tools_info

    async def alist_servers(self) -> List[MCPServer]:
        """Get all servers with connection status and tool information."""
        servers = [s async for s in MCPServer.objects.all().order_by("name")]
        
        # add connection status and tool info to each server
        for server in servers:
            # check if server is connected
            if server.name in self.connected_servers:
                connected_info = self.connected_servers[server.name]
                server.connection_status = "CONNECTED"
                server.connected_at = connected_info["connected_at"]
                server.tool_count = len(connected_info["tools"])
                # convert tools to serializable format
                server.tools = self._serialize_tools(connected_info["tools"])
            else:
                server.connection_status = "DISCONNECTED"
                server.connected_at = None
                server.tool_count = 0
                server.tools = []
        
        return servers

    async def asave_server(
        self,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args_json: Optional[str] = None,
        headers_json: Optional[str] = None,
        query_params_json: Optional[str] = None,
    ) -> MCPServer:
        rec, _ = await MCPServer.objects.aupdate_or_create(
            name=name,
            defaults={
                "transport": transport,
                "url": url,
                "command": command,
                "args_json": args_json,
                "headers_json": headers_json,
                "query_params_json": query_params_json,
                "enabled": True,
            },
        )
        await self.initialize_client()  # re-initialize on change
        return rec

    async def aremove_server(self, name: str) -> bool:
        try:
            rec = await MCPServer.objects.aget(name=name)
            await rec.adelete()
            # Ensure any live connection tracking is cleared
            if name in self.connected_servers:
                try:
                    del self.connected_servers[name]
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
        if not enabled and name in self.connected_servers:
            try:
                del self.connected_servers[name]
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
                args = _safe_json_loads(rec.args_json) or []
                adapter_map[rec.name] = {
                    "command": rec.command or "",
                    "args": [str(x) for x in args if isinstance(args, list)],
                    "transport": "stdio",
                }
            else:
                base_url = rec.url or ""
                if getattr(rec, "query_params_json", None):
                    logging.debug(f"Merging query params for {rec.name}: {rec.query_params_json}")
                    qp = _safe_json_loads(rec.query_params_json)
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
                # attach headers if provided
                if getattr(rec, "headers_json", None):
                    headers = _safe_json_loads(rec.headers_json)
                    if isinstance(headers, dict) and headers:
                        entry["headers"] = headers
                adapter_map[rec.name] = entry
        return adapter_map

    async def initialize_client(self):
        # Restrict adapter map to only explicitly connected servers
        connected_names = list(self.connected_servers.keys())
        self.adapter_map = await self._build_adapter_map(names=connected_names)
        if not self.adapter_map:
            self.client = None
            self.tools = []
            return

        try:
            logging.debug(f"Initializing MCP client with adapter map: {self.adapter_map}")
            self.client = MultiServerMCPClient(self.adapter_map)
            self.tools = await asyncio.wait_for(self.client.get_tools(), timeout=8.0)

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
            tools = await asyncio.wait_for(self.client.get_tools(), timeout=5.0)
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
        Connect to a specific MCP server and return connection status and tools.
        
        Returns:
            Tuple of (success: bool, status_message: str, tools: List[Dict])
        """
        try:
            # check if server exists and is enabled
            server = await MCPServer.objects.aget(name=name)
            if not server.enabled:
                return False, "Server is disabled", []
            
            # build adapter map for this specific server
            adapter_map = await self._build_adapter_map(names=[name])
            if name not in adapter_map:
                return False, "Server configuration not found", []
            
            # create client for this specific server
            server_config = {name: adapter_map[name]}
            client = MultiServerMCPClient(server_config)
            
            # get tools from the server
            tools = await asyncio.wait_for(client.get_tools(), timeout=8.0)
            
            # store connected server info
            self.connected_servers[name] = {
                "client": client,
                "config": adapter_map[name],
                "tools": tools,
                "connected_at": asyncio.get_event_loop().time()
            }
            
            # Convert tools to serializable format
            tools_info = self._serialize_tools(tools)
            
            # rebuild the shared client to include this server
            await self.initialize_client()
            
            return True, "Connected successfully", tools_info
            
        except MCPServer.DoesNotExist:
            return False, "Server not found", []
        except asyncio.TimeoutError:
            return False, "Connection timeout", []
        except Exception as e:
            logging.exception(f"Failed to connect to server {name}: {e}")
            return False, f"Connection failed: {str(e)}", []

    # .. op: disconnect_server
    async def disconnect_server(self, name: str) -> Tuple[bool, str]:
        """
        Disconnect from a specific MCP server.
        
        Returns:
            Tuple of (success: bool, status_message: str)
        """
        try:
            if name not in self.connected_servers:
                return False, "Server not connected"
            
            # get the client and close it if it has a close method
            server_info = self.connected_servers[name]
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
                del self.connected_servers[name]
            except Exception:
                pass

            await self.initialize_client()
            
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


