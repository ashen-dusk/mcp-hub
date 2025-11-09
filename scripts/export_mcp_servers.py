import os
import sys
import json
import django
from datetime import datetime
from django.forms.models import model_to_dict

# --- Setup Django ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # go up one dir from /scripts
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "assistant.settings")  # ✅ <-- change if needed
django.setup()

from app.mcp.models import MCPServer  # ✅ update if model path differs


def to_int_bool(val):
    return 1 if val else 0


def serialize_mcp_server(server):
    """Convert MCPServer instance into JSON-compatible dict matching original export format."""
    return {
        "id": server.id,
        "name": server.name,
        "description": server.description or "",
        "transport": server.transport,
        "url": server.url or "",
        "command": server.command or "",
        "is_public": to_int_bool(server.is_public),
        "args": json.dumps(server.args or {}),
        "headers": json.dumps(server.headers or {}),
        "query_params": json.dumps(server.query_params or {}),
        "tools": json.dumps(server.tools or []),
        "enabled": to_int_bool(server.enabled),
        "requires_oauth2": to_int_bool(server.requires_oauth2),
        "connection_status": "DISCONNECTED",  # DB field isn't stored, ignore for now
        "created_at": server.created_at.isoformat(),
        "updated_at": server.updated_at.isoformat(),
        "owner_id": server.owner_id,
        "category_id": server.category_id,
    }


def export_to_json(out_file="exported_mcp_servers.json"):
    servers = MCPServer.objects.all().order_by("created_at")

    data = [serialize_mcp_server(s) for s in servers]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"✅ Exported {len(data)} MCP servers → {out_file}")


if __name__ == "__main__":
    export_to_json()

# uv run python scripts/export_mcp_servers.py                          
