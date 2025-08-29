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
    # .. field: mcp_servers
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        mcp_servers = await mcp.alist_servers()
        result: List[MCPServerType] = []
        for server in mcp_servers:
            # :: convert tools to ToolInfo objects
            tool_info_list = []
            if server.tools:
                for tool in server.tools:
                    tool_info_list.append(
                        ToolInfo(
                            name=tool["name"],
                            description=tool["description"],
                            schema=tool["schema"],
                        )
                    )
            
            result.append(
                MCPServerType(
                    id=server.id,
                    name=server.name,
                    transport=server.transport,
                    url=server.url,
                    command=server.command,
                    args=server.args,
                    headers=server.headers,
                    query_params=server.query_params,
                    enabled=server.enabled,
                    requires_oauth2=server.requires_oauth2,
                    connection_status=server.connection_status,
                    tools=tool_info_list,
                    updated_at=server.updated_at,
                )
            )
        return result

    @strawberry.field
    # .. field: mcp_server_health
    async def mcp_server_health(self, info: Info, name: str) -> ServerHealthInfo:
        status, tools = await mcp.acheck_server_health(name)
        tool_info_list = [
            ToolInfo(name=t["name"], description=t["description"], schema=t["schema"]) for t in tools
        ]
        return ServerHealthInfo(
            status=status,
            tools=tool_info_list,
        )


@strawberry.type
# ── graphql: mutation ────────────────────────────────────────────────────────
class Mutation:
    @strawberry.mutation
    # .. mutation: save_mcp_server
    async def save_mcp_server(
        self,
        info: Info,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[JSON] = None,
        headers: Optional[JSON] = None,
        query_params: Optional[JSON] = None,
        requires_oauth2: Optional[bool] = False,
    ) -> MCPServerType:
        server = await mcp.asave_server(
            name=name,
            transport=transport,
            url=url,
            command=command,
            args=args,
            headers=headers,
            query_params=query_params,
            requires_oauth2=requires_oauth2,
        )
        return MCPServerType(
            id=server.id,
            name=server.name,
            transport=server.transport,
            url=server.url,
            command=server.command,
            args=server.args,
            headers=server.headers,
            query_params=server.query_params,
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
    # .. mutation: set_mcp_server_enabled
    async def set_mcp_server_enabled(
        self, info: Info, name: str, enabled: bool
    ) -> MCPServerType:
        server = await mcp.aet_server_enabled(name=name, enabled=enabled)
        return MCPServerType(
            id=server.id,
            name=server.name,
            transport=server.transport,
            url=server.url,
            command=server.command,
            args=server.args,
            headers=server.headers,
            query_params=server.query_params,
            enabled=server.enabled,
            requires_oauth2=server.requires_oauth2,
            connection_status="DISCONNECTED",
            tools=[],
            updated_at=server.updated_at,
        )

    @strawberry.mutation
    # .. mutation: connect_mcp_server
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        success, message, tools = await mcp.connect_server(name)
        tool_info_list = [
            ToolInfo(name=t["name"], description=t["description"], schema=t["schema"]) for t in tools
        ]
        
        # :: determine connection status and message
        if success:
            connection_status = "CONNECTED"
            final_message = f"Successfully connected to {name}"
        else:
            connection_status = "FAILED"
            final_message = message
        
        return ConnectionResult(
            success=success,
            message=final_message,
            tools=tool_info_list,
            server_name=name,
            connection_status=connection_status,
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
    # .. mutation: restart_mcp_server
    async def restart_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        status, tools = await mcp.acheck_server_health(name)
        tool_info_list = [
            ToolInfo(name=t["name"], description=t["description"], schema=t["schema"]) for t in tools
        ]
        connection_status = "CONNECTED" if status == "OK" else "FAILED"
        final_message = (
            f"Successfully restarted {name}" if status == "OK" else f"restart failed: {status}"
        )
        return ConnectionResult(
            success=(status == "OK"),
            message=final_message,
            tools=tool_info_list,
            server_name=name,
            connection_status=connection_status,
        )
