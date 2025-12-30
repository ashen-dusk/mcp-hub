import os
import sys
import json
import asyncio
import django

# ---- ✅ Setup Django settings before importing anything Django-related ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # go up one dir from /scripts
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "assistant.settings")  # <-- change if settings module is different
django.setup()

# ---- Now Django is ready ----
from django.contrib.auth import get_user_model
from app.mcp.manager import mcp   # ✅ update if your import path is different
from app.mcp.models import MCPServer

User = get_user_model()


def to_bool(v):
    return bool(int(v)) if isinstance(v, (int, str)) else bool(v)


def parse_json_field(v):
    try:
        return json.loads(v) if isinstance(v, str) else v
    except Exception:
        return {}


async def import_mcp_servers(path):
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"✅ Loaded {len(data)} records")

    for record in data:
        name = record.get("name")
        if not name:
            continue

        # Skip if already exists
        if await MCPServer.objects.filter(name=name).aexists():
            print(f"⏩ Skipped, exists: {name}")
            continue

        owner = None
        if record.get("owner_id"):
            owner = await User.objects.filter(username='himanshu.mehta.sde').afirst()

        created = await mcp.asave_server(
            name=name,
            transport=record.get("transport") or "",
            owner=owner,
            url=record.get("url") or None,
            command=record.get("command") or None,
            args=parse_json_field(record.get("args")),
            headers=parse_json_field(record.get("headers")),
            query_params=parse_json_field(record.get("query_params")),
            requires_oauth2=to_bool(record.get("requires_oauth2")),
            is_public=to_bool(record.get("is_public")),
            description=record.get("description") or None,
            category_ids=record.get("category_ids") or None,
        )

        print(f"✅ Imported: {created.name}")

    print("\n🎉 Done!")


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "exported_mcp_servers.json"
    if not os.path.exists(json_file):
        print(f"Usage: python import_mcp_servers.py <file.json>\nDefaulting to '{json_file}' but it was not found.")
        sys.exit(1)

    asyncio.run(import_mcp_servers(json_file))

# uv run python scripts/import_mcp_servers.py exported_mcp_servers.json