"""
GraphQL schema for Assistant operations.

Provides queries and mutations for managing user assistants and their custom instructions.
"""

from typing import List, Optional
import logging
import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection
from django.contrib.auth.models import User

from app.graphql.permissions import IsAuthenticated
from app.models import Assistant
from app.a2a.client import validate_a2a_agent_url


@strawberry_django.type(Assistant)
class AssistantType:
    """GraphQL type for Assistant model."""
    id: strawberry.ID
    assistant_type: str
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
        assistant_type: str = "orchestrator",
        description: Optional[str] = None,
        config: Optional[strawberry.scalars.JSON] = None,
        is_active: bool = False,
    ) -> AssistantType:
        """
        Create a new assistant for the authenticated user.

        Args:
            name: Display name for the assistant
            instructions: Custom instructions to control assistant behavior
            assistant_type: Type of assistant (orchestrator, specialist, tool_agent)
            description: Optional description
            config: Optional JSON configuration (for A2A agents: { "a2a_url": "http://...", "skills": [...] })
            is_active: Whether this assistant should be active (only one can be active per user)
        """
        user: User = info.context.request.user
        assistant = await Assistant.objects.acreate(
            user=user,
            name=name,
            assistant_type=assistant_type,
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
        assistant_type: Optional[str] = None,
        instructions: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[strawberry.scalars.JSON] = None,
        is_active: Optional[bool] = None,
    ) -> AssistantType:
        """
        Update an existing assistant (must belong to authenticated user).

        Only provided fields will be updated.
        If config contains 'a2a_agents', each agent URL will be validated before saving.
        """
        user: User = info.context.request.user
        try:
            assistant = await Assistant.objects.aget(pk=id, user=user)

            if name is not None:
                assistant.name = name
            if assistant_type is not None:
                assistant.assistant_type = assistant_type
            if instructions is not None:
                assistant.instructions = instructions
            if description is not None:
                assistant.description = description
            if config is not None:
                # Merge with existing config instead of replacing
                existing_config = assistant.config if isinstance(assistant.config, dict) else {}
                updated_config = {**existing_config, **config}

                # Validate A2A agent URLs if present in config
                if isinstance(updated_config, dict) and 'a2a_agents' in updated_config:
                    a2a_agents = updated_config['a2a_agents']
                    if not isinstance(a2a_agents, list):
                        raise ValueError("a2a_agents must be a list")

                    validated_agents = []
                    for idx, agent in enumerate(a2a_agents):
                        if not isinstance(agent, dict):
                            raise ValueError(f"Agent at index {idx} must be a dictionary")

                        # Validate required fields
                        if 'url' not in agent or not agent['url']:
                            raise ValueError(f"Agent at index {idx} must have a 'url' field")
                        if 'name' not in agent or not agent['name']:
                            raise ValueError(f"Agent at index {idx} must have a 'name' field")
                        if 'description' not in agent or not agent['description']:
                            raise ValueError(f"Agent at index {idx} must have a 'description' field")

                        # Validate URL by calling the A2A agent
                        try:
                            await validate_a2a_agent_url(agent['url'])
                            logging.info(f"Successfully validated A2A agent URL: {agent['url']}")
                        except Exception as e:
                            logging.error(f"A2A agent URL validation failed for {agent['url']}: {e}")
                            raise ValueError(f"Invalid A2A agent URL at index {idx}: {str(e)}")

                        # Store only name, description, url after validation
                        validated_agents.append({
                            "name": agent['name'].strip(),
                            "description": agent['description'].strip(),
                            "url": agent['url'].strip()
                        })

                    # Replace with validated agents
                    updated_config['a2a_agents'] = validated_agents

                assistant.config = updated_config
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
