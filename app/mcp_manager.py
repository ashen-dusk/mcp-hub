import json
import asyncio
import logging
import ast
from typing import Dict, List, Optional, Any
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


class MCP:
    def __init__(self):
        self.client: Optional[MultiServerMCPClient] = None
        self.adapter_map: Dict[str, Dict[str, Any]] = {}
        self.tools: List[Any] = []
    
    async def alist_servers(self) -> List[MCPServer]:
        return [s async for s in MCPServer.objects.all().order_by("name")]

    async def aadd_server(
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
        except MCPServer.DoesNotExist:
            return False
        rec.enabled = False
        await rec.asave(update_fields=["enabled", "updated_at"])
        await self.initialize_client()  # re-initialize on change
        return True

    async def _build_adapter_map(self) -> Dict[str, Dict[str, Any]]:
        adapter_map: Dict[str, Dict[str, Any]] = {}
        async for rec in MCPServer.objects.filter(enabled=True).all():
            print(f"DEBUG: rec: {rec.query_params_json}")
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
                    print(f"DEBUG: rec.query_params_json: {rec.query_params_json}")
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
                            print(f"DEBUG: base_url: {base_url}")
                        except Exception as e:
                            logging.warning(f"DEBUG: error merging query params: {e}")

                entry: Dict[str, Any] = {
                    "url": base_url,
                    "transport": rec.transport,
                }
                # attach headers if provided
                if getattr(rec, "headers_json", None):
                    headers = _safe_json_loads(rec.headers_json)
                    if isinstance(headers, dict) and headers:
                        entry["headers"] = headers
                # add default Accept header for SSE
                if rec.transport == MCPServer.TRANSPORT_SSE:
                    headers = entry.get("headers", {})
                    if "Accept" not in headers:
                        headers["Accept"] = "text/event-stream"
                    entry["headers"] = headers
                adapter_map[rec.name] = entry
        return adapter_map

    async def initialize_client(self):
        self.adapter_map = await self._build_adapter_map()
        if not self.adapter_map:
            self.client = None
            self.tools = []
            return

        try:
            print(f"Initializing MCP client with adapter map: {self.adapter_map}")
            self.client = MultiServerMCPClient(self.adapter_map)
            self.tools = await asyncio.wait_for(self.client.get_tools(), timeout=8.0)

        except asyncio.TimeoutError:
            logging.warning("MCP client initialization or tool fetching timed out.")
            self.client = None
            self.tools = []
        except Exception as e:
            logging.exception(f"Failed to initialize MCP client: {e}")
            self.client = None
            self.tools = []

    async def acheck_server_health(self, name: str) -> str:
        try:
            server = await MCPServer.objects.aget(name=name)
        except MCPServer.DoesNotExist:
            return "NOT_FOUND"

        if not server.enabled:
            return "DISABLED"

        try:
            adapter_map = await self._build_adapter_map()
            if name not in adapter_map:
                return "ERROR"

            server_config = {name: adapter_map[name]}
            client = MultiServerMCPClient(server_config)
            await asyncio.wait_for(client.get_tools(), timeout=5.0)
            return "OK"
        except asyncio.TimeoutError:
            return "TIMEOUT"
        except Exception as e:
            logging.warning(f"Health check for {name} failed: {e}")
            return "ERROR"

    def get_client(self) -> Optional[MultiServerMCPClient]:
        return self.client

    def get_tools(self) -> List[Any]:
        return self.tools


# Global instance
mcp = MCP()


