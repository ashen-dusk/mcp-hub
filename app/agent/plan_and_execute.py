"""
Simplified Plan-and-Execute Agent

This is a streamlined implementation based on the LangGraph tutorial pattern:
- Planner: Creates a list of steps
- Executor: Executes each step
- Replanner: Optionally adjusts the plan based on results

The architecture is intentionally simple and follows the LangGraph tutorial pattern.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Literal
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.types import AgentState, Plan, PlanStep
from app.agent.model import get_llm
from app.agent.chat import get_tools
from copilotkit.langgraph import copilotkit_customize_config, copilotkit_emit_state

logger = logging.getLogger(__name__)


# ============================================================================
# State Management
# ============================================================================

def get_plan_state_for_frontend(state: AgentState) -> Dict[str, Any]:
    """
    Convert agent state to frontend-friendly plan state.
    This state is emitted to the UI for real-time updates.
    """
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)

    if not plan:
        return {
            "mode": "simple",
            "status": "idle"
        }

    steps = []
    completed = 0
    failed = 0
    in_progress = 0
    pending = 0

    for i, step in enumerate(plan.steps):
        is_current = i == current_step_index
        steps.append({
            "step_number": step.step_number,
            "description": step.description,
            "expected_outcome": step.expected_outcome,
            "status": step.status,
            "dependencies": step.dependencies,
            "result": step.result,
            "error": step.error,
            "is_current": is_current
        })

        if step.status == "completed":
            completed += 1
        elif step.status == "failed":
            failed += 1
        elif step.status == "in_progress":
            in_progress += 1
        elif step.status == "pending":
            pending += 1

    total = len(plan.steps)
    percentage = int((completed / total) * 100) if total > 0 else 0

    return {
        "mode": "plan",
        "status": state.get("status", "planning"),
        "plan": {
            "objective": plan.objective,
            "summary": plan.plan_summary or "",
            "created_at": plan.created_at,
            "updated_at": plan.updated_at
        },
        "progress": {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "current_step_index": current_step_index,
            "percentage": percentage
        },
        "steps": steps
    }


# ============================================================================
# Planner Node
# ============================================================================

class PlannerOutput(BaseModel):
    """Structured output from the planner."""
    steps: List[str] = Field(description="List of step descriptions")


async def plan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Creates a plan by breaking down the user's request into steps.

    Simple and focused - just generates a list of steps to execute.
    """
    logger.info("=== Planning ===")

    messages = state.get("messages", [])
    sessionId = state.get("sessionId")

    # Get user query
    user_query = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    if not user_query:
        logger.warning("No user query found")
        return state

    # Get available tools
    tools = await get_tools(sessionId=sessionId)
    tool_descriptions = "\n".join([
        f"- {tool.name}: {getattr(tool, 'description', 'No description')}"
        for tool in tools
    ])

    # Planning prompt
    system_prompt = f"""You are a task planner. Break down the user's request into clear, sequential steps.

Available Tools:
{tool_descriptions}

Create a plan with 3-7 steps. Each step should be:
- Clear and specific
- Actionable with available tools
- Ordered logically

Return ONLY a JSON object with this format:
{{
    "steps": [
        "Step 1 description",
        "Step 2 description",
        "Step 3 description"
    ]
}}"""

    llm = get_llm(state)

    try:
        # Try structured output
        if hasattr(llm, 'with_structured_output'):
            structured_llm = llm.with_structured_output(PlannerOutput)
            response = await structured_llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Create a plan for: {user_query}")
            ])
            step_descriptions = response.steps
        else:
            # Fallback: parse JSON
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Create a plan for: {user_query}")
            ])
            import json
            response_text = response.content if hasattr(response, 'content') else str(response)
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                step_descriptions = parsed.get("steps", [])
            else:
                raise ValueError("No JSON found in response")

        # Create Plan object
        plan = Plan(
            objective=user_query,
            plan_summary=f"Plan with {len(step_descriptions)} steps",
            steps=[
                PlanStep(
                    step_number=i + 1,
                    description=desc,
                    dependencies=[],
                    expected_outcome=f"Complete step {i + 1}",
                    status="pending"
                )
                for i, desc in enumerate(step_descriptions)
            ],
            created_at=datetime.now().isoformat()
        )

        logger.info(f"Created plan with {len(plan.steps)} steps")

        # Emit state to frontend using CopilotKit
        # config = copilotkit_customize_config(
        #     config,
        #     emit_intermediate_state=[{
        #         "state_key": "plan_state",
        #         "tool": "__plan_state__"
        #     }]
        # )

        new_state = {
            **state,
            "plan": plan,
            "current_step_index": 0,
            "plan_state": get_plan_state_for_frontend({**state, "plan": plan, "current_step_index": 0}),
            "messages": [
                *messages,
                AIMessage(content=f"I've created a plan with {len(plan.steps)} steps:\n\n" +
                         "\n".join([f"{i+1}. {step.description}" for i, step in enumerate(plan.steps)]))
            ]
        }

        # await copilotkit_emit_state(config, new_state)

        return new_state

    except Exception as e:
        logger.error(f"Planning error: {e}", exc_info=True)
        # Fallback: single-step plan
        plan = Plan(
            objective=user_query,
            plan_summary="Direct execution",
            steps=[
                PlanStep(
                    step_number=1,
                    description=user_query,
                    dependencies=[],
                    expected_outcome="Complete the task",
                    status="pending"
                )
            ],
            created_at=datetime.now().isoformat()
        )

        new_state = {
            **state,
            "plan": plan,
            "current_step_index": 0,
            "plan_state": get_plan_state_for_frontend({**state, "plan": plan, "current_step_index": 0}),
            "messages": [*messages, AIMessage(content="Let me work on that.")]
        }

        return new_state


# ============================================================================
# Executor Node
# ============================================================================

async def execute_step_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Executes a single step from the plan.

    Gets the current step, executes it with LLM + tools, updates status.
    """
    logger.info("=== Executing Step ===")

    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)
    messages = state.get("messages", [])
    sessionId = state.get("sessionId")

    if not plan or current_step_index >= len(plan.steps):
        return state

    current_step = plan.steps[current_step_index]
    logger.info(f"Executing step {current_step.step_number}: {current_step.description}")

    # Update step status
    current_step.status = "in_progress"

    # Emit updated state
    config = copilotkit_customize_config(
        config,
        emit_intermediate_state=[{
            "state_key": "plan_state",
            "tool": "__plan_state__"
        }]
    )

    updated_state = {
        **state,
        "plan_state": get_plan_state_for_frontend(state)
    }
    # await copilotkit_emit_state(config, updated_state)

    # Get tools
    tools = await get_tools(sessionId=sessionId)

    # Execute step with LLM
    llm = get_llm(state)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    system_prompt = f"""You are executing step {current_step.step_number} of a plan.

Current Step: {current_step.description}
Expected Outcome: {current_step.expected_outcome}

Focus ONLY on this specific step. Use tools if needed. Be thorough but concise."""

    try:
        response = await llm_with_tools.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Execute: {current_step.description}")
        ], config=config)

        # Check for tool calls
        tool_calls = getattr(response, "tool_calls", [])

        if tool_calls:
            # Tool execution needed - will be handled by ToolNode
            return {
                **state,
                "messages": [*messages, response],
                "needs_tools": True
            }
        else:
            # Step completed without tools
            result = response.content if hasattr(response, 'content') else str(response)
            current_step.status = "completed"
            current_step.result = result

            logger.info(f"Step {current_step.step_number} completed")

            # Move to next step
            next_index = current_step_index + 1

            new_state = {
                **state,
                "plan": plan,
                "current_step_index": next_index,
                "messages": [
                    *messages,
                    AIMessage(content=f"✓ Completed step {current_step.step_number}: {result[:200]}...")
                ],
                "plan_state": get_plan_state_for_frontend({
                    **state,
                    "plan": plan,
                    "current_step_index": next_index
                }),
                "needs_tools": False
            }

            # await copilotkit_emit_state(config, new_state)

            return new_state

    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        current_step.status = "failed"
        current_step.error = str(e)

        return {
            **state,
            "plan": plan,
            "current_step_index": current_step_index + 1,
            "messages": [
                *messages,
                AIMessage(content=f"✗ Step {current_step.step_number} failed: {str(e)}")
            ],
            "plan_state": get_plan_state_for_frontend({**state, "plan": plan}),
            "needs_tools": False
        }


# ============================================================================
# Tool Execution Node
# ============================================================================

async def tool_execution_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Executes tools called by the executor.
    """
    from langgraph.prebuilt import ToolNode

    logger.info("=== Executing Tools ===")

    sessionId = state.get("sessionId")
    tools = await get_tools(sessionId=sessionId)

    tool_node = ToolNode(tools)
    result = await tool_node.ainvoke(state, config)

    # Get current step and mark as completed
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)

    if plan and current_step_index < len(plan.steps):
        current_step = plan.steps[current_step_index]
        current_step.status = "completed"
        current_step.result = "Tools executed successfully"

        # Emit updated state
        config = copilotkit_customize_config(
            config,
            emit_intermediate_state=[{
                "state_key": "plan_state",
                "tool": "__plan_state__"
            }]
        )

        next_index = current_step_index + 1

        new_state = {
            **result,
            "plan": plan,
            "current_step_index": next_index,
            "plan_state": get_plan_state_for_frontend({
                **state,
                "plan": plan,
                "current_step_index": next_index
            }),
            "needs_tools": False
        }

        # await copilotkit_emit_state(config, new_state)

        return new_state

    return {
        **result,
        "needs_tools": False
    }


# ============================================================================
# Replan Node (Optional)
# ============================================================================

async def replan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Optionally replans if steps failed or new approach needed.

    Simplified: Only replans if critical failure occurred.
    """
    logger.info("=== Replanning ===")

    plan = state.get("plan")
    if not plan:
        return state

    failed_steps = [step for step in plan.steps if step.status == "failed"]

    if not failed_steps:
        return state

    # Simple replan: add a recovery step
    recovery_step = PlanStep(
        step_number=len(plan.steps) + 1,
        description=f"Recover from failed step: {failed_steps[0].description}",
        dependencies=[],
        expected_outcome="Successfully recover and complete task",
        status="pending"
    )

    plan.steps.append(recovery_step)
    plan.updated_at = datetime.now().isoformat()

    return {
        **state,
        "plan": plan,
        "plan_state": get_plan_state_for_frontend(state)
    }


# ============================================================================
# Routing
# ============================================================================

def should_continue(state: AgentState) -> Literal["execute_step", "tools", "replan", "end"]:
    """
    Route after execution:
    - Continue to next step
    - Execute tools if needed
    - Replan if failure
    - End if all complete
    """
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)
    needs_tools = state.get("needs_tools", False)

    if needs_tools:
        return "tools"

    if not plan:
        return "end"

    # Check if more steps remain
    if current_step_index < len(plan.steps):
        return "execute_step"

    # Check for failures that need replanning
    failed_steps = [step for step in plan.steps if step.status == "failed"]
    if failed_steps:
        return "replan"

    return "end"


def route_after_tools(state: AgentState) -> Literal["execute_step", "end"]:
    """Route after tool execution."""
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)

    if plan and current_step_index < len(plan.steps):
        return "execute_step"

    return "end"


# ============================================================================
# Graph Construction
# ============================================================================

def create_plan_graph():
    """
    Create simplified plan-and-execute graph.

    Flow:
    START -> plan -> execute_step -> [tools?] -> execute_step -> ... -> END
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("execute_step", execute_step_node)
    workflow.add_node("tools", tool_execution_node)
    workflow.add_node("replan", replan_node)

    # Set entry point
    workflow.add_edge(START, "plan")

    # Plan -> Execute
    workflow.add_edge("plan", "execute_step")

    # Execute -> Route
    workflow.add_conditional_edges(
        "execute_step",
        should_continue,
        {
            "execute_step": "execute_step",
            "tools": "tools",
            "replan": "replan",
            "end": END
        }
    )

    # Tools -> Route
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "execute_step": "execute_step",
            "end": END
        }
    )

    # Replan -> Execute
    workflow.add_edge("replan", "execute_step")

    return workflow.compile(checkpointer=MemorySaver())


# Create graph instance
simplified_plan_graph = create_plan_graph()

logger.info("Simplified plan-and-execute graph created")
