"""
Seed script for populating Category data in the MCP Hub.

This script creates all standard categories with icons, colors, and descriptions.
The icons reference PNG files served from the Next.js frontend.

Usage:
    python seed_categories.py

Requirements:
    - Django environment must be configured
    - Database must be migrated
    - Run from mcp-hub directory with virtual environment activated
"""

import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'assistant.settings')
django.setup()

from app.mcp.models import Category


# Category data with icon paths, colors, and descriptions
CATEGORIES = [
    {
        "name": "AI & Machine Learning",
        "icon": "ai-and-ml.png",
        "color": "#9C27B0",  # Purple
        "description": "Artificial intelligence, machine learning models, LLMs, and ML infrastructure tools"
    },
    {
        "name": "API & Integration",
        "icon": "api-and-integration.png",
        "color": "#FF9800",  # Orange
        "description": "REST APIs, GraphQL, webhooks, third-party integrations, and API management tools"
    },
    {
        "name": "Cloud & Infrastructure",
        "icon": "cloud-and-infrastructure.png",
        "color": "#2196F3",  # Blue
        "description": "Cloud platforms, infrastructure as code, container orchestration, and DevOps tools"
    },
    {
        "name": "Communication",
        "icon": "communication.png",
        "color": "#4CAF50",  # Green
        "description": "Messaging platforms, email services, notifications, and team collaboration tools"
    },
    {
        "name": "Content & Media",
        "icon": "content-and-media.png",
        "color": "#E91E63",  # Pink
        "description": "Content management systems, media processing, image/video editing, and digital asset management"
    },
    {
        "name": "Data & Analytics",
        "icon": "data-and-analytics.png",
        "color": "#00BCD4",  # Cyan
        "description": "Data pipelines, business intelligence, analytics platforms, and data visualization tools"
    },
    {
        "name": "Database",
        "icon": "database.png",
        "color": "#FF5722",  # Deep Orange
        "description": "SQL and NoSQL databases, database management tools, data warehousing, and caching systems"
    },
    {
        "name": "Development",
        "icon": "development.png",
        "color": "#673AB7",  # Deep Purple
        "description": "IDEs, code editors, version control, CI/CD, testing frameworks, and development utilities"
    },
    {
        "name": "Productivity",
        "icon": "productivity.png",
        "color": "#FFC107",  # Amber
        "description": "Task management, project planning, note-taking, time tracking, and workflow automation tools"
    },
    {
        "name": "Security",
        "icon": "security.png",
        "color": "#F44336",  # Red
        "description": "Authentication, authorization, encryption, security scanning, and compliance tools"
    },
    {
        "name": "Other",
        "icon": "other.png",
        "color": "#607D8B",  # Blue Grey
        "description": "Miscellaneous tools and services that don't fit into other categories"
    },
]


def seed_categories():
    """
    Create or update categories in the database.

    This function is idempotent - running it multiple times won't create duplicates.
    Existing categories with the same name will be updated with new values.
    """
    print("🌱 Starting category seed...")
    print("-" * 60)

    created_count = 0
    updated_count = 0

    for category_data in CATEGORIES:
        category, created = Category.objects.update_or_create(
            name=category_data["name"],
            defaults={
                "icon": category_data["icon"],
                "color": category_data["color"],
                "description": category_data["description"],
            }
        )

        if created:
            created_count += 1
            print(f"✅ Created: {category.name} (ID: {category.id})")
        else:
            updated_count += 1
            print(f"🔄 Updated: {category.name} (ID: {category.id})")

    print("-" * 60)
    print(f"✨ Seed complete!")
    print(f"   • Created: {created_count} categories")
    print(f"   • Updated: {updated_count} categories")
    print(f"   • Total:   {Category.objects.count()} categories in database")
    print("\n📊 All categories:")

    for cat in Category.objects.all():
        print(f"   - {cat.name} ({cat.id}) - {cat.color}")


def clear_categories():
    """
    WARNING: Delete all categories from the database.

    This will set category fields to NULL for all MCP servers that reference them.
    Use with caution!
    """
    count = Category.objects.count()
    Category.objects.all().delete()
    print(f"🗑️  Deleted {count} categories")


if __name__ == "__main__":
    import sys

    # Check for --clear flag
    if "--clear" in sys.argv:
        print("⚠️  WARNING: This will delete ALL categories!")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            clear_categories()
        else:
            print("❌ Cancelled")
        sys.exit(0)

    # Check for --help flag
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("\nOptions:")
        print("  --clear    Delete all categories (requires confirmation)")
        print("  --help     Show this help message")
        sys.exit(0)

    # Run the seed
    seed_categories()
