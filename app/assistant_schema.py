"""
GraphQL schema for Assistant operations.

Provides queries and mutations for managing user assistants and their custom instructions.
"""

from typing import List, Optional
import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection
from django.contrib.auth.models import User

from app.graphql.permissions import IsAuthenticated
from app.models import Assistant


@strawberry_django.type(Assistant)
class AssistantType:
    """GraphQL type for Assistant model."""
    id: strawberry.ID
    name: str
    description: Optional[str]
    instructions: str
    is_active: bool
    config: strawberry.scalars.JSON
    created_at: strawberry.auto
    updated_at: strawberry.auto


@strawberry_django.filter_type(Assistant, lookups=True)
class AssistantFilter:
    """Filters for querying assistants."""
    name: strawberry.auto
    instructions: strawberry.auto


@strawberry_django.order_type(Assistant)
class AssistantOrder:
    """Ordering options for assistants."""
    name: strawberry.auto
    created_at: strawberry.auto
    updated_at: strawberry.auto


@strawberry.type
class Query:

    @strawberry_django.field(permission_classes=[IsAuthenticated])
    async def my_assistants(self, info: Info) -> List[AssistantType]:
        """
        Get all assistants belonging to the authenticated user.
        """
        user: User = info.context.request.user
        assistants = [assistant async for assistant in Assistant.objects.filter(user=user)]
        return assistants

    @strawberry_django.field(permission_classes=[IsAuthenticated])
    async def my_assistant(self, info: Info, id: strawberry.ID) -> Optional[AssistantType]:
        """
        Get a specific assistant by ID (must belong to authenticated user).
        """
        user: User = info.context.request.user
        try:
            return await Assistant.objects.aget(pk=id, user=user)
        except Assistant.DoesNotExist:
            return None


@strawberry.type
class Mutation:

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def create_assistant(
        self,
        info: Info,
        name: str,
        instructions: str,
        description: Optional[str] = None,
        config: Optional[strawberry.scalars.JSON] = None,
        is_active: bool = False,
    ) -> AssistantType:
        """
        Create a new assistant for the authenticated user.

        Args:
            name: Display name for the assistant
            instructions: Custom instructions to control assistant behavior
            description: Optional description
            config: Optional JSON configuration
            is_active: Whether this assistant should be active (only one can be active per user)
        """
        user: User = info.context.request.user
        assistant = await Assistant.objects.acreate(
            user=user,
            name=name,
            instructions=instructions,
            description=description,
            config=config or {},
            is_active=is_active,
        )
        return assistant

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def update_assistant(
        self,
        info: Info,
        id: strawberry.ID,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[strawberry.scalars.JSON] = None,
        is_active: Optional[bool] = None,
    ) -> AssistantType:
        """
        Update an existing assistant (must belong to authenticated user).

        Only provided fields will be updated.
        """
        user: User = info.context.request.user
        try:
            assistant = await Assistant.objects.aget(pk=id, user=user)

            if name is not None:
                assistant.name = name
            if instructions is not None:
                assistant.instructions = instructions
            if description is not None:
                assistant.description = description
            if config is not None:
                assistant.config = config
            if is_active is not None:
                assistant.is_active = is_active

            await assistant.asave()
            return assistant
        except Assistant.DoesNotExist:
            raise Exception(f"Assistant with id {id} not found or does not belong to you")

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def delete_assistant(self, info: Info, id: strawberry.ID) -> bool:
        """
        Delete an assistant (must belong to authenticated user).
        """
        user: User = info.context.request.user
        try:
            assistant = await Assistant.objects.aget(pk=id, user=user)
            await assistant.adelete()
            return True
        except Assistant.DoesNotExist:
            return False
