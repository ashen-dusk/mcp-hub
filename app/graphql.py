from typing import List, Optional

import strawberry
from strawberry.types import Info

from .mcp_manager import mcp_manager
from .models import MCPServer
from .types import MCPServerType


@strawberry.type
class Query:
    @strawberry.field
    def mcp_servers(self, info: Info) -> List[MCPServerType]:
        rows = mcp_manager.list_servers()
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


@strawberry.type
class Mutation:
    @strawberry.mutation
    def add_mcp_server(
        self,
        info: Info,
        name: str,
        transport: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args_json: Optional[str] = None,
    ) -> MCPServerType:
        rec = mcp_manager.add_server(
            name=name,
            transport=transport,
            url=url,
            command=command,
            args_json=args_json,
        )
        return MCPServerType(
            name=rec.name,
            transport=rec.transport,
            url=rec.url,
            command=rec.command,
            args_json=rec.args_json,
        )

    @strawberry.mutation
    def remove_mcp_server(self, info: Info, name: str) -> bool:
        return mcp_manager.remove_server(name)


schema = strawberry.Schema(Query, Mutation)


