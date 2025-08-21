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
    ServerHealthInfo
)

@strawberry.type
class Query:
    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        rows = await mcp.alist_servers()
        result: List[MCPServerType] = []
        for r in rows:
            # convert tools to ToolInfo objects
            tool_info_list = []
            for tool in r.tools:
                tool_info_list.append(
                    ToolInfo(
                        name=tool["name"],
                        description=tool["description"],
                        schema=tool["schema"],  # Already a JSON string from manager
                    )
                )
            
            result.append(
                MCPServerType(
                    name=r.name,
                    transport=r.transport,
                    url=r.url,
                    command=r.command,
                    args_json=r.args_json,
                    enabled=r.enabled,
                    connection_status=r.connection_status,
                    connected_at=r.connected_at,
                    tool_count=r.tool_count,
                    tools=tool_info_list,
                )
            )
        return result

    @strawberry.field
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
class Mutation:
    @strawberry.mutation
    async def save_mcp_server(
        self,
        info: Info,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args_json: Optional[str] = None,
        headers_json: Optional[str] = None,
        query_params_json: Optional[str] = None,
    ) -> MCPServerType:
        rec = await mcp.asave_server(
            name=name,
            transport=transport,
            url=url,
            command=command,
            args_json=args_json,
            headers_json=headers_json,
            query_params_json=query_params_json,
        )
        return MCPServerType(
            name=rec.name,
            transport=rec.transport,
            url=rec.url,
            command=rec.command,
            args_json=rec.args_json,
            enabled=rec.enabled,
            connection_status="DISCONNECTED",
            connected_at=None,
            tool_count=0,
            tools=[],
        )

    @strawberry.mutation
    async def remove_mcp_server(self, info: Info, name: str) -> bool:
        return await mcp.aremove_server(name)

    @strawberry.mutation
    async def set_mcp_server_enabled(
        self, info: Info, name: str, enabled: bool
    ) -> MCPServerType:
        rec = await mcp.aet_server_enabled(name=name, enabled=enabled)
        return MCPServerType(
            name=rec.name,
            transport=rec.transport,
            url=rec.url,
            command=rec.command,
            args_json=rec.args_json,
            enabled=rec.enabled,
            connection_status="DISCONNECTED",
            connected_at=None,
            tool_count=0,
            tools=[],
        )

    @strawberry.mutation
    async def connect_mcp_server(self, info: Info, name: str) -> ConnectionResult:
        success, message, tools = await mcp.connect_server(name)
        print(f"Success: {success}, Message: {message}, Tools: {tools}")
        tool_info_list = [
            ToolInfo(name=t["name"], description=t["description"], schema=t["schema"]) for t in tools
        ]
        
        # determine connection status and message
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
    async def disconnect_mcp_server(self, info: Info, name: str) -> DisconnectResult:
        success, message = await mcp.disconnect_server(name)
        return DisconnectResult(
            success=success,
            message=message,
        )
