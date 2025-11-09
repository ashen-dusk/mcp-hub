"""
Plan-and-Execute Agent

Implementation using tools with predict_state metadata to avoid JSON in chat.
Based on CopilotKit agentic generative UI pattern.

Flow:
1. Planner: Generate a list of steps using create_plan tool
2. Agent: Execute current step with tools
3. Replan: Adjust remaining plan using update_plan tool
4. Repeat until done
"""

import logging
from typing import Dict, Any, List, Literal, Annotated
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from app.agent.types import AgentState
from app.agent.chat import get_tools

logger = logging.getLogger(__name__)


# ============================================================================
# Tool Models
# ============================================================================

class PlanStep(BaseModel):
    """A step in the plan."""
    description: str = Field(description="The step description")
    status: str = Field(description="The status of the step", default="pending")


# ============================================================================
# Planning and Replanning Tools
# ============================================================================

@tool
def create_plan(
    steps: Annotated[
        List[PlanStep],
        "An array of step objects, each containing description and status (always 'pending')"
    ]
):
    """
    Create a step-by-step plan to solve the user's request.
    Each step should be a clear, actionable task ordered logically.
    The status should always be 'pending' for new plans.
    """
    # This tool doesn't actually execute anything - it just receives the plan
    # The tool call will be streamed to frontend via predict_state
    return "Plan created successfully"


@tool
def update_plan(
    steps: Annotated[
        List[PlanStep],
        "An array of remaining step objects that still need to be executed"
    ]
):
    """
    Update the plan with remaining steps based on execution results.
    Only include steps that are truly still needed (excluding completed ones).
    The status should always be 'pending' for remaining steps.
    """
    # This tool doesn't actually execute anything - it just receives the updated plan
    # The tool call will be streamed to frontend via predict_state
    return "Plan updated successfully"


# ============================================================================
# Planner Node
# ============================================================================

async def plan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Generate a step-by-step plan from the user's input using create_plan tool.
    Returns: plan (list of strings), past_steps (empty initially)
    """
    logger.info("=== Planning ===")

    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""

    system_prompt = """You are a planning assistant. Create a simple step-by-step plan to solve the user's request.

You MUST call the function `create_plan` that was provided to you.

Guidelines:
- Each step should be a clear, actionable task
- Steps should be ordered logically
- Don't add unnecessary steps
- The final step should produce the answer
- After calling the function, give a very brief summary (one sentence) of your plan."""

    # Configure predict_state metadata to stream tool calls to frontend
    if config is None:
        config = RunnableConfig(recursion_limit=25)

    config["metadata"] = config.get("metadata", {})
    config["metadata"]["predict_state"] = [{
        "state_key": "plan",
        "tool": "create_plan",
        "tool_argument": "steps",
    }]

    # Create LLM with create_plan tool
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    llm_with_tools = llm.bind_tools([create_plan], parallel_tool_calls=False)

    # Generate plan
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input)
    ], config)

    # Extract plan from tool call
    steps = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_call = response.tool_calls[0]
        if tool_call.get("name") == "create_plan":
            steps = [
                step["description"]
                for step in tool_call.get("args", {}).get("steps", [])
            ]
            logger.info(f"Created plan with {len(steps)} steps: {steps}")

            # Add tool response message
            tool_response = ToolMessage(
                content="Plan created.",
                tool_call_id=tool_call.get("id"),
                name="create_plan"
            )

            # Continue conversation for LLM to provide summary
            summary_response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
                response,
                tool_response
            ], config)

            return {
                "plan": steps,
                "past_steps": [],
                "messages": messages + [response, tool_response, summary_response]
            }

    # Fallback if no tool call
    logger.warning("No plan created")
    return {
        "plan": [],
        "past_steps": [],
        "messages": messages + [response]
    }


# ============================================================================
# Agent/Executor Node
# ============================================================================

async def agent_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Execute the current step using tools.

    Uses LangGraph's built-in create_react_agent which handles the ReAct loop
    (reasoning and acting) automatically until the task is complete.
    """
    logger.info("=== Executing Step ===")

    plan = state.get("plan", [])
    past_steps = state.get("past_steps", [])
    messages = state.get("messages", [])
    sessionId = state.get("sessionId")

    if not plan:
        logger.warning("No plan found")
        return state

    # Get current step (first in remaining plan)
    current_step = plan[0]
    logger.info(f"Executing: {current_step}")

    # Get tools
    tools = await get_tools(sessionId=sessionId)

    # Build context from past steps
    context = ""
    if past_steps:
        context = "Previous steps completed:\n"
        for step, result in past_steps:
            context += f"- {step}: {result}\n"
        context += "\n"

    # Create prompt for this step
    prompt = f"""{context}Current step: {current_step}

Execute this step using available tools and provide detailed results."""

    # Create ReAct agent (handles tool execution loop automatically)
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    agent = create_react_agent(llm, tools)

    # Execute the step
    logger.info("Starting agent execution...")
    result_state = await agent.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config=config
    )

    # Extract final result from agent messages
    agent_messages = result_state.get("messages", [])
    if agent_messages:
        final_message = agent_messages[-1]
        result = final_message.content if hasattr(final_message, 'content') else str(final_message)
    else:
        result = "No result returned from agent"

    logger.info(f"Step result: {result[:200]}...")

    # Add to past steps and remove current step from plan
    new_past_steps = past_steps + [(current_step, result)]
    # Remove the executed step from the plan
    new_plan = plan[1:] if len(plan) > 1 else []

    return {
        "past_steps": new_past_steps,
        "plan": new_plan,  # Update plan to remove executed step
        "messages": messages  # Keep original conversation messages
    }



# ============================================================================
# Replan Node
# ============================================================================

async def replan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Replan based on execution results using update_plan tool.

    Reviews what's been done and decides:
    - Respond to user if task is complete, OR
    - Update the plan with remaining steps
    """
    logger.info("=== Replanning ===")

    plan = state.get("plan", [])
    past_steps = state.get("past_steps", [])
    messages = state.get("messages", [])

    user_input = messages[0].content if messages else ""

    # Build summary of progress
    progress = ""
    if past_steps:
        progress = "Steps completed:\n"
        for step, result in past_steps:
            progress += f"- {step}: {result[:200]}...\n"  # Truncate long results

    # Calculate remaining steps in original plan
    num_completed = len(past_steps)
    remaining = plan

    logger.info(f"Completed {num_completed} steps, {len(remaining)} remaining in plan")

    # Check if task is complete (no more steps in plan)
    if not remaining or len(remaining) == 0:
        logger.info("No remaining steps - task complete")

        final_prompt = f"""Original objective: {user_input}

All steps have been completed:
{progress}

Provide a final response to the user summarizing what was accomplished."""

        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        final_response = await llm.ainvoke([
            SystemMessage(content="You are a helpful assistant providing final summaries."),
            HumanMessage(content=final_prompt)
        ], config)

        return {
            "response": final_response.content,
            "messages": messages + [final_response]
        }

    # Otherwise, ask LLM to update the plan
    system_prompt = f"""You are a replanning assistant. Review the progress and update the plan.

Original objective: {user_input}

Steps Already Completed ({num_completed}):
{progress}

Original Remaining Steps ({len(remaining)}):
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(remaining)])}

You MUST call the function `update_plan` with the remaining steps that still need to be done.

IMPORTANT:
- Do NOT repeat any of the {num_completed} completed steps above
- Only include steps that are truly still needed
- You can modify/simplify remaining steps based on what was learned
- If the task is complete, provide an empty array to update_plan

After calling the function, give a very brief status update (one sentence)."""

    # Configure predict_state metadata
    if config is None:
        config = RunnableConfig(recursion_limit=25)

    config["metadata"] = config.get("metadata", {})
    config["metadata"]["predict_state"] = [{
        "state_key": "plan",
        "tool": "update_plan",
        "tool_argument": "steps",
    }]

    # Create LLM with update_plan tool
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    llm_with_tools = llm.bind_tools([update_plan], parallel_tool_calls=False)

    # Get updated plan
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content="What should we do next?")
    ], config)

    # Extract updated plan from tool call
    new_plan = None
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_call = response.tool_calls[0]
        if tool_call.get("name") == "update_plan":
            new_plan = [
                step["description"]
                for step in tool_call.get("args", {}).get("steps", [])
            ]
            logger.info(f"Updated plan with {len(new_plan)} remaining steps")

            # Add tool response
            tool_response = ToolMessage(
                content="Plan updated.",
                tool_call_id=tool_call.get("id"),
                name="update_plan"
            )

            # If plan is empty, task is complete
            if not new_plan or len(new_plan) == 0:
                logger.info("Updated plan is empty - task complete")

                # Get final summary
                summary_response = await llm.ainvoke([
                    SystemMessage(content="Provide a brief final summary of what was accomplished."),
                    HumanMessage(content=f"Original objective: {user_input}\n\nCompleted steps:\n{progress}")
                ], config)

                return {
                    "response": summary_response.content,
                    "plan": [],
                    "messages": messages + [response, tool_response, summary_response]
                }

            # Continue with updated plan
            summary_response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content="What should we do next?"),
                response,
                tool_response
            ], config)

            return {
                "plan": new_plan,
                "messages": messages + [response, tool_response, summary_response]
            }

    # Fallback - continue with existing plan
    logger.warning("No plan update received")
    return state


# ============================================================================
# Routing Logic
# ============================================================================

def should_continue(state: AgentState) -> Literal["agent", "__end__"]:
    """
    Decide whether to continue executing or end.

    - If we have a response, we're done -> END
    - If we still have a plan, continue -> agent
    """
    # Check if there's a final response
    if state.get("response"):
        logger.info("Task complete, ending")
        return "__end__"

    # Check if there are remaining steps in plan
    plan = state.get("plan", [])
    if plan:
        logger.info(f"Continuing with {len(plan)} remaining steps")
        return "agent"

    # No plan and no response -> end
    logger.info("No plan or response, ending")
    return "__end__"


# ============================================================================
# Graph Construction
# ============================================================================

def create_plan_and_execute_graph():
    """
    Create plan-and-execute graph using tools with predict_state.

    Flow:
        START -> plan -> agent -> replan -> [continue?]
                            ↑________________|
                                             |
                                           END

    - plan: Generate initial plan using create_plan tool
    - agent: Execute current step with tools
    - replan: Review progress, update plan using update_plan tool
    - Loop until task is complete
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("replan", replan_node)

    # Define edges
    workflow.add_edge(START, "plan")       # Start with planning
    workflow.add_edge("plan", "agent")     # After planning -> execute
    workflow.add_edge("agent", "replan")   # After execution -> replan

    # Conditional routing after replan
    workflow.add_conditional_edges(
        "replan",
        should_continue,
        {
            "agent": "agent",      # Continue with next step
            "__end__": END         # Task complete
        }
    )

    return workflow.compile(checkpointer=MemorySaver())


# Create graph instance
plan_and_execute_graph = create_plan_and_execute_graph()

logger.info("Plan-and-execute graph created with tool-based planning")
