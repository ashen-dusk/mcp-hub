from typing import Any, Optional, Dict, List
from langgraph.graph import MessagesState
from copilotkit import CopilotKitState
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """Represents a single step in the execution plan."""

    step_number: int = Field(description="Step number in the plan")
    description: str = Field(description="Description of what this step should accomplish")
    dependencies: List[int] = Field(
        default_factory=list,
        description="List of step numbers that must be completed before this step"
    )
    expected_outcome: str = Field(description="Expected outcome or result of this step")
    status: str = Field(
        default="pending",
        description="Status: pending, in_progress, completed, failed, skipped"
    )
    result: Optional[str] = Field(
        default=None,
        description="Actual result after execution"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if step failed"
    )


class Plan(BaseModel):
    """Represents the complete execution plan."""

    objective: str = Field(description="Overall objective/goal of the plan")
    steps: List[PlanStep] = Field(
        default_factory=list,
        description="List of steps to execute"
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    plan_summary: Optional[str] = Field(
        default=None,
        description="Human-readable summary of the plan"
    )


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
    plan: Optional[Plan] = Field(
        default=None,
        description="Current execution plan"
    )
    current_step_index: int = Field(
        default=0,
        description="Index of the current step being executed"
    )
    execution_mode: str = Field(
        default="simple",
        description="Execution mode: 'simple' for direct execution, 'plan' for plan-and-execute"
    )
    plan_approved: bool = Field(
        default=False,
        description="Whether the plan has been approved by user (if human-in-the-loop)"
    )
    task_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context for the overall task"
    )
    execution_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="History of step executions with results"
    )
    needs_tools: bool = Field(
        default=False,
        description="Whether the current step needs tool execution"
    )
    plan_state: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Frontend-formatted plan state for UI rendering"
    )