from typing import List, Optional

import strawberry
from strawberry.types import Info

from app.mcp.manager import mcp
from app.mcp.models import MCPServer
from app.mcp.types import MCPServerType


@strawberry.type
class Query:
    @strawberry.field
    async def mcp_servers(self, info: Info) -> List[MCPServerType]:
        rows = await mcp.alist_servers()
        result: List[MCPServerType] = []
        for r in rows:
            result.append(
                MCPServerType(
                    name=r.name,
                    transport=r.transport,
                    url=r.url,
                    command=r.command,
                    args_json=r.args_json,
                )
            )
        return result

    @strawberry.field
    async def mcp_server_health(self, info: Info, name: str) -> str:
        return await mcp.acheck_server_health(name)


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
        )
