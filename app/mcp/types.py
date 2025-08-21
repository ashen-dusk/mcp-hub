import strawberry
from datetime import datetime
from typing import Optional, List, Dict, Any
from strawberry.scalars import JSON

# ── graphql: types ────────────────────────────────────────────────────────────
@strawberry.type
class ToolInfo:
    name: str
    description: str
    schema: JSON

@strawberry.type
class MCPServerType:
    id: strawberry.ID
    name: str
    transport: str
    url: Optional[str]
    command: Optional[str]
    args: Optional[JSON]
    headers: Optional[JSON]
    query_params: Optional[JSON]
    enabled: bool
    connection_status: str
    tools: List[ToolInfo]
    updated_at: datetime

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



