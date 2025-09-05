import strawberry
from strawberry import auto, ID
import strawberry_django
from datetime import datetime
from typing import Optional, List, Dict, Any
from strawberry.scalars import JSON
from .models import MCPServer

# ── graphql: types ────────────────────────────────────────────────────────────
@strawberry.type
class ToolInfo:
    name: str
    description: Optional[str]
    schema: JSON

@strawberry_django.filter_type(MCPServer, lookups=True)
class MCPServerFilter:
    id: auto
    name: auto
    transport: auto
    enabled: auto
    requires_oauth2: auto
    connection_status: auto
    is_shared: auto

@strawberry_django.type(MCPServer, filters=MCPServerFilter)
class MCPServerType:
    id: ID
    name: str
    transport: str
    url: Optional[str]
    command: Optional[str]
    args: Optional[JSON]
    enabled: bool
    requires_oauth2: bool
    connection_status: str
    tools: List[ToolInfo]
    updated_at: datetime
    owner: Optional[str] 
    is_shared: bool

@strawberry.type
class ConnectionResult:
    success: bool
    message: str
    tools: List[ToolInfo]
    server_name: str
    connection_status: str

@strawberry.type
class DisconnectResult:
    success: bool
    message: str

@strawberry.type
class ServerHealthInfo:
    status: str
    tools: List[ToolInfo]



