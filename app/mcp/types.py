import strawberry
from typing import Optional, List, Dict, Any

# ── graphql: types ────────────────────────────────────────────────────────────
@strawberry.type
class ToolInfo:
    name: str
    description: str
    schema: str

@strawberry.type
class MCPServerType:
    name: str
    transport: str
    url: Optional[str]
    command: Optional[str]
    args_json: Optional[str]
    enabled: bool
    connection_status: str
    connected_at: Optional[float]
    tool_count: int
    tools: List[ToolInfo]

@strawberry.type
# .. type: ConnectionResult
class ConnectionResult:
    success: bool
    message: str
    tools: List[ToolInfo]
    server_name: str
    connection_status: str

@strawberry.type
# .. type: DisconnectResult
class DisconnectResult:
    success: bool
    message: str

@strawberry.type
# .. type: ServerHealthInfo
class ServerHealthInfo:
    status: str
    tools: List[ToolInfo]



