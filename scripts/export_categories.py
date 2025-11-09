import os
import sys
import json
import django

# --- Setup Django ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "assistant.settings")  # ✅ update if needed
django.setup()

from app.mcp.models import Category  # ✅ update import path if different


def serialize_category(cat):
    return {
        "id": str(cat.id),
        "name": cat.name,
        "slug": cat.slug,
        "icon": cat.icon or "",
        "color": cat.color or "",
        "created_at": cat.created_at.isoformat(),
        "updated_at": cat.updated_at.isoformat(),
    }


def export_categories(out_file="exported_categories.json"):
    categories = Category.objects.all().order_by("name")
    data = [serialize_category(cat) for cat in categories]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"✅ Exported {len(data)} categories → {out_file}")


if __name__ == "__main__":
    export_categories()

# uv run python scripts/export_categories.py                           
