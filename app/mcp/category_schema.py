"""
GraphQL schema for Category operations.

Provides queries and mutations for managing categories.
"""

from typing import List, Optional
import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from app.graphql.permissions import IsAuthenticated
from app.mcp.models import Category
from app.mcp.types import CategoryType, CategoryFilter, CategoryOrder


@strawberry.type
class Query:

    @strawberry_django.connection(DjangoListConnection[CategoryType], filters=CategoryFilter, order=CategoryOrder)
    def categories(self) -> List[Category]:
        """
        Get all categories with Relay-style pagination, filtering, and ordering.

        Examples:
        - Filter by name: categories(filters: { name: { exact: "productivity" } })
        - Search by name: categories(filters: { name: { iContains: "data" } })
        - Order by name: categories(order: { name: ASC })
        """
        return Category.objects.all()

    @strawberry_django.field
    def category(self, id: strawberry.ID) -> Optional[CategoryType]:
        """Get a single category by ID."""
        try:
            return Category.objects.get(pk=id)
        except Category.DoesNotExist:
            return None


@strawberry.type
class Mutation:

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def create_category(
        self,
        info: Info,
        name: str,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CategoryType:
        """
        Create a new category.

        Args:
            name: Unique category name
            icon: Icon identifier (URL, emoji, icon name, or icon class)
            color: Color code for UI display (hex, rgb, or color name)
            description: Description of this category
        """
        category = await Category.objects.acreate(
            name=name,
            icon=icon,
            color=color,
            description=description,
        )
        return category

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def update_category(
        self,
        info: Info,
        id: strawberry.ID,
        name: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CategoryType:
        """
        Update an existing category.

        Only provided fields will be updated.
        """
        try:
            category = await Category.objects.aget(pk=id)

            if name is not None:
                category.name = name
            if icon is not None:
                category.icon = icon
            if color is not None:
                category.color = color
            if description is not None:
                category.description = description

            await category.asave()
            return category
        except Category.DoesNotExist:
            raise Exception(f"Category with id {id} not found")

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def delete_category(self, info: Info, id: strawberry.ID) -> bool:
        """
        Delete a category.

        Note: Servers linked to this category will have their category field set to NULL.
        """
        try:
            category = await Category.objects.aget(pk=id)
            await category.adelete()
            return True
        except Category.DoesNotExist:
            return False
