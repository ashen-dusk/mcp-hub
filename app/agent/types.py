from typing import Any, Optional, Dict, List, Annotated
from langgraph.graph import MessagesState
from copilotkit import CopilotKitState
from pydantic import BaseModel, Field
from langchain_core.tools import tool


class PlanStep(BaseModel):
    """A step in the plan."""
    description: str = Field(description="The step description")
    status: str = Field(description="The status of the step", default="pending")


class AgentState(CopilotKitState):
    """Conversation state for the agent with plan-and-execute support."""

    # Original fields
    model: str
    status: Optional[str] = None
    sessionId: Optional[str] = None
    tool_calls: Optional[Any] = None
    assistant: Optional[Dict[str, Any]] = None
    approval_response: Optional[Dict[str, Any]] = None
    current_tool_call: Optional[Dict[str, Any]] = None

    # Plan-and-Execute fields
    plan: Optional[List[str]] = Field(
        default=None,
        description="List of remaining step descriptions to execute"
    )
    past_steps: Optional[List[tuple]] = Field(
        default_factory=list,
        description="List of (step, result) tuples for completed steps"
    )
    response: Optional[str] = Field(
        default=None,
        description="Final response when task is complete"
    )


# ============================================================================
# Tools
# ============================================================================

@tool
def create_plan(
    steps: Annotated[List[PlanStep], "Array of step objects with description and status"]
):
    """Create a step-by-step plan to solve the user's request."""
    return "Plan created successfully"


@tool
def update_plan(
    steps: Annotated[List[PlanStep], "Array of remaining step objects"]
):
    """Update the plan with remaining steps based on execution results."""
    return "Plan updated successfully"


@tool
def human_input(
    prompt: Annotated[str, "The question to show to the human"],
    context: Annotated[str, "Additional context"] = ""
):
    """
    Request input from the human user. Use when you need clarification,
    additional information, confirmation, or user choices.
    """
    return "Waiting for human input"