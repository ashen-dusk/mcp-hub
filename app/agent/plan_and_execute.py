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

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from app.agent.types import AgentState, PlanStep, create_plan
from app.agent.model import get_llm
from app.agent.chat import get_tools
from langgraph.prebuilt import ToolNode

# from copilotkit.langgraph import copilotkit_customize_config, copilotkit_emit_state

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
    """Create initial plan from user query."""
    logger.info("=== Planning ===")

    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""

    system_prompt = """Create a clear step-by-step plan for the user's request.
    Call the `create_plan` function with your plan. Keep steps simple and actionable."""

    # Configure predict_state for UI streaming
    if config is None:
        config = RunnableConfig(recursion_limit=25)
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["predict_state"] = [{
        "state_key": "plan",
        "tool": "create_plan",
        "tool_argument": "steps",
    }]

    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    llm_with_tools = llm.bind_tools([create_plan], parallel_tool_calls=False)

    response = await llm_with_tools.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input)
    ], config)

    # Extract plan
    steps = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_call = response.tool_calls[0]
        if tool_call.get("name") == "create_plan":
            steps = [step["description"] for step in tool_call.get("args", {}).get("steps", [])]
            logger.info(f"Created plan with {len(steps)} steps")

            tool_msg = ToolMessage(
                content="Plan created.",
                tool_call_id=tool_call.get("id"),
                name="create_plan"
            )

            summary = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
                response,
                tool_msg
            ], config)

            return {
                "plan": steps,
                "past_steps": [],
                "messages": messages + [response, tool_msg, summary]
            }

    return {"plan": [], "past_steps": [], "messages": messages + [response]}


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
    # config = copilotkit_customize_config(
    #     config,
    #     emit_intermediate_state=[{
    #         "state_key": "plan_state",
    #         "tool": "__plan_state__"
    #     }]
    # )

    # updated_state = {
    #     **state,
    #     "plan_state": get_plan_state_for_frontend(state)
    # }
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
        # Include full message history so LLM can see previous tool results
        conversation = [
            SystemMessage(content=system_prompt),
            *messages,  # Include all previous messages (including ToolMessages)
            HumanMessage(content=f"Execute: {current_step.description}")
        ]
        response = await llm_with_tools.ainvoke(conversation, config=config)

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

    Tool results are added to messages so the LLM can interpret them
    in the next execution or replan step.
    """
    logger.info("=== Executing Tools ===")

    sessionId = state.get("sessionId")
    tools = await get_tools(sessionId=sessionId)

    tool_node = ToolNode(tools)
    result = await tool_node.ainvoke(state, config)

    # Mark current step as completed and move to next
    # The replanner will analyze tool results and adjust if needed
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)

    if plan and current_step_index < len(plan.steps):
        current_step = plan.steps[current_step_index]
        current_step.status = "completed"

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

        return new_state

    return {
        **result,
        "needs_tools": False
    }


# ============================================================================
# Replan Node (Optional)
# ============================================================================

class ReplanOutput(BaseModel):
    """Structured output from the replanner."""
    analysis: str = Field(description="Analysis of progress so far")
    should_modify_plan: bool = Field(description="Whether the plan needs modification")
    remaining_steps: List[str] = Field(description="Updated list of remaining step descriptions")


async def replan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Dynamically replans based on execution results (Tutorial Pattern).

    After each step, analyzes:
    - What was accomplished
    - Whether objective is already met
    - What remaining steps are actually needed
    - Whether to add/remove/modify steps
    """
    logger.info("=== Replanning ===")

    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)
    messages = state.get("messages", [])
    sessionId = state.get("sessionId")

    if not plan:
        logger.info("No plan found, skipping replan")
        return state

    # Check if all steps are complete
    if current_step_index >= len(plan.steps):
        logger.info("All steps complete, no replanning needed")
        return state

    # Get completed steps
    completed_steps = [step for step in plan.steps[:current_step_index] if step.status == "completed"]
    failed_steps = [step for step in plan.steps[:current_step_index] if step.status == "failed"]
    remaining_steps = plan.steps[current_step_index:]

    logger.info(f"📊 Progress: {len(completed_steps)} completed, {len(failed_steps)} failed, {len(remaining_steps)} remaining")

    # Build context for replanner
    progress_summary = "\n".join([
        f"✓ Step {step.step_number}: {step.description} - {step.result or 'Completed'}"
        for step in completed_steps
    ])

    if failed_steps:
        progress_summary += "\n" + "\n".join([
            f"✗ Step {step.step_number}: {step.description} - Failed: {step.error}"
            for step in failed_steps
        ])

    remaining_summary = "\n".join([
        f"- Step {step.step_number}: {step.description}"
        for step in remaining_steps
    ])

    # Get available tools
    tools = await get_tools(sessionId=sessionId)

    # Replan prompt (tools will be bound to LLM)
    system_prompt = f"""You are a task replanner. Analyze the progress and decide if the remaining plan needs adjustment.

Original Objective: {plan.objective}

Progress So Far:
{progress_summary}

Remaining Planned Steps:
{remaining_summary}

Based on what's been accomplished, determine:
1. Is the objective already met? (can we skip remaining steps?)
2. Do remaining steps still make sense?
3. Should we add new steps based on results?
4. Should we modify/remove steps that are no longer needed?

Return a JSON object:
{{
    "analysis": "Brief analysis of progress and what's needed",
    "should_modify_plan": true/false,
    "remaining_steps": ["updated step 1", "updated step 2", ...]
}}

If objective is met or no changes needed, return empty remaining_steps: []"""

    llm = get_llm(state)

    # Bind tools so LLM is aware of capabilities without explicitly listing them
    llm_with_tools = llm.bind_tools(tools)

    try:
        # Include full message history so LLM can see tool results and previous interactions
        conversation = [
            SystemMessage(content=system_prompt),
            *messages,  # Include all messages (including ToolMessages with results)
            HumanMessage(content=f"Analyze progress and update the plan if needed.")
        ]

        # Try structured output with tool-aware LLM
        if hasattr(llm_with_tools, 'with_structured_output'):
            structured_llm = llm_with_tools.with_structured_output(ReplanOutput)
            response = await structured_llm.ainvoke(conversation)
            analysis = response.analysis
            should_modify = response.should_modify_plan
            updated_steps = response.remaining_steps
        else:
            # Fallback: parse JSON
            response = await llm_with_tools.ainvoke(conversation)
            import json
            response_text = response.content if hasattr(response, 'content') else str(response)
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                analysis = parsed.get("analysis", "")
                should_modify = parsed.get("should_modify_plan", False)
                updated_steps = parsed.get("remaining_steps", [])
            else:
                raise ValueError("No JSON found in response")

        logger.info(f"🔄 Replan Analysis: {analysis}")
        logger.info(f"📝 Should modify: {should_modify}, Updated steps: {len(updated_steps)}")

        if should_modify and updated_steps:
            # Create new plan steps
            new_steps = [
                PlanStep(
                    step_number=current_step_index + i + 1,
                    description=desc,
                    dependencies=[],
                    expected_outcome=f"Complete step {current_step_index + i + 1}",
                    status="pending"
                )
                for i, desc in enumerate(updated_steps)
            ]

            # Update plan: keep completed steps + new remaining steps
            plan.steps = plan.steps[:current_step_index] + new_steps
            plan.updated_at = datetime.now().isoformat()

            logger.info(f"✨ Plan updated: {len(new_steps)} remaining steps")

        elif not updated_steps:
            # Objective met, clear remaining steps
            plan.steps = plan.steps[:current_step_index]
            plan.updated_at = datetime.now().isoformat()
            logger.info("🎯 Objective met! No remaining steps needed")

        return {
            **state,
            "plan": plan,
            "plan_state": get_plan_state_for_frontend(state)
        }

    except Exception as e:
        logger.error(f"Replanning error: {e}", exc_info=True)
        # Fallback: keep plan as-is
        return state


# ============================================================================
# Routing
# ============================================================================

def should_continue(state: AgentState) -> Literal["tools", "replan", "end"]:
    """
    Route after execution (Tutorial Pattern):
    - Execute tools if needed
    - Always replan after step execution (adaptive planning)
    - End if no plan exists
    """
    plan = state.get("plan")
    needs_tools = state.get("needs_tools", False)

    if needs_tools:
        return "tools"

    if not plan:
        return "end"

    # ALWAYS replan after each step execution
    # This enables dynamic plan adjustment based on results
    return "replan"


def route_after_tools(state: AgentState) -> Literal["replan", "end"]:
    """Route after tool execution - go to replan for adaptive planning."""
    plan = state.get("plan")

    if plan:
        return "replan"

    return "end"


def replan_route(state: AgentState) -> Literal["execute_step", "end"]:
    """
    Route after replanning.

    Decides whether to:
    - Continue executing remaining steps
    - End if objective is met or no steps remain
    """
    plan = state.get("plan")
    current_step_index = state.get("current_step_index", 0)

    if not plan:
        return "end"

    # Check if there are more steps to execute
    if current_step_index < len(plan.steps):
        return "execute_step"

    return "end"


# ============================================================================
# Graph Construction
# ============================================================================

def create_plan_graph():
    """
    Create adaptive plan-and-execute graph (Tutorial Pattern).

    Flow:
    START -> plan -> execute_step -> replan -> execute_step -> replan -> ... -> END
                          ↓
                        tools
                          ↓
                       replan

    After each step execution, the plan is dynamically adjusted based on:
    - What was accomplished
    - Whether the objective is already met
    - What remaining steps are actually needed
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("execute_step", execute_step_node)
    workflow.add_node("tools", tool_execution_node)
    workflow.add_node("replan", replan_node)

    # Set entry point
    workflow.add_edge(START, "plan")

    # Plan -> Execute first step
    workflow.add_edge("plan", "execute_step")

    # Execute -> Route (tools needed? -> replan -> end)
    workflow.add_conditional_edges(
        "execute_step",
        should_continue,
        {
            "tools": "tools",
            "replan": "replan",
            "end": END
        }
    )

    # Tools -> Always replan (adaptive planning)
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "replan": "replan",
            "end": END
        }
    )

    # Replan -> Route (continue? -> execute_step : end)
    workflow.add_conditional_edges(
        "replan",
        replan_route,
        {
            "execute_step": "execute_step",
            "end": END
        }
    )

    return workflow.compile(checkpointer=MemorySaver())


# Create graph instance
plan_and_execute_graph = create_plan_graph()

logger.info("Simplified plan-and-execute graph created")
