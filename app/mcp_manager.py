import json
from typing import Dict, List, Optional, Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from .models import MCPServer


class MCPConnectionManager:
    
    def list_servers(self) -> List[MCPServer]:
        return list(MCPServer.objects.all().order_by("name"))

    def add_server(
        self,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args_json: Optional[str] = None,
    ) -> MCPServer:
        rec, _ = MCPServer.objects.update_or_create(
            name=name,
            defaults={
                "transport": transport,
                "url": url,
                "command": command,
                "args_json": args_json,
                "enabled": True,
            },
        )
        return rec

    def remove_server(self, name: str) -> bool:
        try:
            rec = MCPServer.objects.get(name=name)
        except MCPServer.DoesNotExist:
            return False
        rec.enabled = False
        rec.save(update_fields=["enabled", "updated_at"])
        return True

    def _build_adapter_map(self) -> Dict[str, Dict[str, Any]]:
        adapter_map: Dict[str, Dict[str, Any]] = {}
        for rec in MCPServer.objects.filter(enabled=True).all():
            if rec.transport == "stdio":
                args: List[str] = []
                if rec.args_json:
                    try:
                        parsed = json.loads(rec.args_json)
                        if isinstance(parsed, list):
                            args = [str(x) for x in parsed]
                    except Exception:
                        args = []
                adapter_map[rec.name] = {
                    "command": rec.command or "",
                    "args": args,
                    "transport": "stdio",
                }
            else:
                adapter_map[rec.name] = {
                    "url": rec.url or "",
                    "transport": rec.transport,
                }
        return adapter_map

    def get_langchain_tools(self) -> List[Any]:
        adapter_map = self._build_adapter_map()
        if not adapter_map:
            return []
        client = MultiServerMCPClient(adapter_map)
        return client.get_tools()


mcp_manager = MCPConnectionManager()


