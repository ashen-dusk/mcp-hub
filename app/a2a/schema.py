"""
GraphQL schema for A2A agent operations.

Provides mutations for validating A2A agents via /.well-known/agent-card.json
"""

from typing import Optional
import strawberry
from strawberry.types import Info
import logging

from app.graphql.permissions import IsAuthenticated
from app.a2a.client import validate_a2a_agent_url

logger = logging.getLogger(__name__)


@strawberry.type
class A2AValidationResult:
    """Result of A2A agent validation."""
    success: bool
    agent_card: Optional[strawberry.scalars.JSON] = None
    error: Optional[str] = None


@strawberry.type
class Query:
    """A2A-related queries."""

    @strawberry.field
    def a2a_test(self) -> str:
        """Test query for A2A schema."""
        return "A2A schema loaded"


@strawberry.type
class Mutation:
    """A2A-related mutations."""

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def validate_a2a_agent(
        self,
        info: Info,
        agent_url: str
    ) -> A2AValidationResult:
        """
        Validate an A2A agent by fetching and parsing /.well-known/agent-card.json

        Args:
            agent_url: Base URL of the A2A agent (e.g., http://localhost:9001)

        Returns:
            A2AValidationResult with agent metadata if valid, or error message if invalid
        """
        try:
            # Validate the agent URL
            agent_data = await validate_a2a_agent_url(agent_url)

            logger.info(f"Successfully validated A2A agent: {agent_data.get('name')}")

            return A2AValidationResult(
                success=True,
                agent_card=agent_data,
                error=None
            )

        except Exception as e:
            error_msg = f"Failed to validate A2A agent: {str(e)}"
            logger.error(error_msg)

            return A2AValidationResult(
                success=False,
                agent_card=None,
                error=error_msg
            )
