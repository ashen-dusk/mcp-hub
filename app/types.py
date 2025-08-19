import strawberry
from typing import Optional


@strawberry.type
class MCPServerType:
    name: str
    transport: str
    url: Optional[str]
    command: Optional[str]
    args_json: Optional[str]


