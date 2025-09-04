from typing import List, Optional

import strawberry
from strawberry.types import Info

from app.mcp.manager import mcp
from app.mcp.models import MCPServer
from app.mcp.types import (
    MCPServerType, 
    ConnectionResult, 
    DisconnectResult, 
    ToolInfo,
    ServerHealthInfo,
    JSON
)

@strawberry.type
# ── graphql: query ───────────────────────────────────────────────────────────
class Query:
    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        servers = await mcp.alist_servers()
        return [
            MCPServerType(
                id=server.id,
                name=server.name,
                transport=server.transport,
                url=server.url,
                command=server.command,
                args=server.args,
                enabled=server.enabled,
                requires_oauth2=server.requires_oauth2,
                connection_status=server.connection_status,
                tools=[
                    ToolInfo(name=t["name"], description=t.get("description") or "", schema=t["schema"])
                    for t in server.tools or []
                ],
                updated_at=server.updated_at,
            )
            for server in servers
        ]

    @strawberry.field
    async def mcp_server_health(self, info: Info, name: str) -> ServerHealthInfo:
        status, tools = await mcp.acheck_server_health(name)
        return ServerHealthInfo(
            status=status,
            tools=[ToolInfo(name=t["name"], description=t.get("description") or "", schema=t["schema"]) for t in tools],
        )


@strawberry.type
# ── graphql: mutation ────────────────────────────────────────────────────────
class Mutation:
    @strawberry.mutation
    async def save_mcp_server(
        self, info: Info, name: str, transport: str,
        url: Optional[str] = None, command: Optional[str] = None,
        args: Optional[JSON] = None, headers: Optional[JSON] = None,
        query_params: Optional[JSON] = None, requires_oauth2: Optional[bool] = False,
    ) -> MCPServerType:
        server = await mcp.asave_server(name, transport, url, command, args, headers, query_params, requires_oauth2)
        return MCPServerType(
            id=server.id, 
            name=server.name, 
            transport=server.transport, 
            url=server.url,
            command=server.command, 
            args=server.args, 
            enabled=server.enabled,
            requires_oauth2=server.requires_oauth2, 
            connection_status="DISCONNECTED",
            tools=[], 
            updated_at=server.updated_at,
        )

    @strawberry.mutation
    # .. mutation: remove_mcp_server
    async def remove_mcp_server(self, info: Info, name: str) -> bool:
        return await mcp.aremove_server(name)

    @strawberry.mutation
    async def set_mcp_server_enabled(self, info: Info, name: str, enabled: bool) -> MCPServerType:
        server = await mcp.aet_server_enabled(name=name, enabled=enabled)
        return MCPServerType(
            id=server.id, 
            name=server.name, 
            transport=server.transport, 
            url=server.url,
            command=server.command, 
            args=server.args, 
            enabled=server.enabled,
            requires_oauth2=server.requires_oauth2, 
            connection_status="DISCONNECTED",
            tools=server.tools, 
            updated_at=server.updated_at,
        )

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        success, message, tools = await mcp.connect_server(name)
        return ConnectionResult(
            success=success,
            message=f"Successfully connected to {name}" if success else message,
            tools=[ToolInfo(name=t["name"], description=t.get("description") or "", schema=t["schema"]) for t in tools],
            server_name=name,
            connection_status="CONNECTED" if success else "FAILED",
        )

    @strawberry.mutation
    # .. mutation: disconnect_mcp_server
    async def disconnect_mcp_server(self, info: Info, name: str) -> DisconnectResult:
        success, message = await mcp.disconnect_server(name)
        return DisconnectResult(
            success=success,
            message=message,
        )

    @strawberry.mutation
    async def restart_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        status, tools = await mcp.acheck_server_health(name)
        success = status == "OK"
        return ConnectionResult(
            success=success,
            message=f"Successfully restarted {name}" if success else f"restart failed: {status}",
            tools=[ToolInfo(name=t["name"], description=t.get("description") or "", schema=t["schema"]) for t in tools],
            server_name=name,
            connection_status="CONNECTED" if success else "FAILED",
        )
