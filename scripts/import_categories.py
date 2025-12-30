import os
import sys
import json
import django

# --- Setup Django ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "assistant.settings")  # ✅ update if needed
django.setup()

from app.mcp.models import Category  # ✅ update import path if needed


def import_categories(json_file):
    if not os.path.exists(json_file):
        print(f"❌ File not found: {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"✅ Loaded {len(data)} categories")

    for record in data:
        cat_id = record.get("id")
        slug = record.get("slug")

        # Skip if category already exists
        if Category.objects.filter(id=cat_id).exists() or Category.objects.filter(slug=slug).exists():
            print(f"⏩ Skipped (exists): {record['name']}")
            continue

        Category.objects.create(
            id=cat_id,
            name=record.get("name"),
            slug=slug,
            icon=record.get("icon") or None,
            color=record.get("color") or None,
        )

        print(f"✅ Imported: {record['name']}")

    print("\n🎉 Done importing categories!")


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "exported_categories.json"
    if not os.path.exists(json_file):
        print(f"Usage: python import_categories.py <file.json>\nDefaulting to '{json_file}' but it was not found.")
        sys.exit(1)

    import_categories(json_file)

# uv run python scripts/import_categories.py exported_categories.json  
