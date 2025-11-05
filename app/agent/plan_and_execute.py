"""
Plan-and-Execute Agent

Simple implementation following the LangGraph tutorial pattern:
https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/plan-and-execute/plan-and-execute.ipynb

Flow:
1. Planner: Generate a list of steps
2. Agent: Execute current step with tools
3. Replan: Adjust remaining plan based on results
4. Repeat until done
"""

import logging
from typing import Dict, Any, List, Literal, Union
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from app.agent.types import AgentState
from app.agent.chat import get_tools

logger = logging.getLogger(__name__)


# ============================================================================
# Structured Output Models
# ============================================================================

class Plan(BaseModel):
    """Plan is just a list of steps."""
    steps: List[str] = Field(description="Step-by-step plan as a list of strings")


class Response(BaseModel):
    """Response to send back to user."""
    response: str = Field(description="Final response to user")


class Act(BaseModel):
    """Action: either respond to user OR continue with updated plan."""
    action: Union[Response, Plan] = Field(
        description="Use Response if task is complete. Use Plan to continue with remaining steps."
    )


# ============================================================================
# Planner Node
# ============================================================================

async def plan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Generate a step-by-step plan from the user's input.
    Returns: plan (list of strings), past_steps (empty initially)
    """
    logger.info("=== Planning ===")

    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""

    system_prompt = """You are a planning assistant. Create a simple step-by-step plan to solve the user's request.

Guidelines:
- Each step should be a clear, actionable task
- Steps should be ordered logically
- Don't add unnecessary steps
- The final step should produce the answer"""

    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    structured_llm = llm.with_structured_output(Plan)

    plan_result = await structured_llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input)
    ])

    steps = plan_result.steps
    logger.info(f"Created plan with {len(steps)} steps: {steps}")

    return {
        "plan": steps,
        "past_steps": [],
        "messages": messages
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

    # Add to past steps
    new_past_steps = past_steps + [(current_step, result)]

    return {
        "past_steps": new_past_steps,
        "messages": messages  # Keep original conversation messages
    }


# ============================================================================
# OLD IMPLEMENTATION (kept for reference)
# ============================================================================
# async def agent_node_old(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
#     """
#     OLD VERSION: Called LLM once without executing tools.
#     Problem: Tools were never actually invoked, just planned.
#     """
#     logger.info("=== Executing Step ===")
#
#     plan = state.get("plan", [])
#     past_steps = state.get("past_steps", [])
#     sessionId = state.get("sessionId")
#
#     if not plan:
#         logger.warning("No plan found")
#         return state
#
#     current_step = plan[0]
#     logger.info(f"Executing: {current_step}")
#
#     tools = await get_tools(sessionId=sessionId)
#
#     context = ""
#     if past_steps:
#         context = "Previous steps completed:\n"
#         for step, result in past_steps:
#             context += f"- {step}: {result}\n"
#         context += "\n"
#
#     llm = ChatOpenAI(model="gpt-4o", temperature=0)
#     llm_with_tools = llm.bind_tools(tools)
#
#     prompt = f"""{context}Current step: {current_step}
#
# Execute this step and provide the result."""
#
#     response = await llm_with_tools.ainvoke([HumanMessage(content=prompt)])
#     result = response.content if hasattr(response, 'content') else str(response)
#
#     logger.info(f"Step result: {result[:100]}...")
#
#     new_past_steps = past_steps + [(current_step, result)]
#
#     return {
#         "past_steps": new_past_steps
#     }


# ============================================================================
# Replan Node
# ============================================================================

async def replan_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Replan based on execution results.

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
    # Since agent_node executes plan[0], we need to skip already-executed steps
    num_completed = len(past_steps)
    remaining = plan[num_completed:] if num_completed < len(plan) else []

    logger.info(f"Completed {num_completed} steps, {len(remaining)} remaining in original plan")

    system_prompt = f"""You are a replanning assistant. Review the progress and decide the next action.

Original objective: {user_input}

Steps Already Completed ({num_completed}):
{progress}

Original Remaining Steps from Initial Plan ({len(remaining)}):
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(remaining)])}

Decide:
- If the objective is COMPLETE and you can answer the user, use Response with your final answer
- If MORE steps are needed, use Plan with ONLY the steps that still need to be done (excluding any already completed)

IMPORTANT:
- Do NOT repeat any of the {num_completed} completed steps above
- Only include steps that are truly still needed
- You can modify/simplify remaining steps based on what was learned"""

    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    structured_llm = llm.with_structured_output(Act)

    result = await structured_llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content="What should we do next?")
    ])

    action = result.action

    # Check if it's a Response (task complete)
    if isinstance(action, Response):
        logger.info(f"Task complete: {action.response}")
        return {
            "response": action.response,
            "messages": messages + [AIMessage(content=action.response)]
        }

    # Otherwise it's a Plan (continue with updated steps)
    elif isinstance(action, Plan):
        new_plan = action.steps
        logger.info(f"Updated plan with {len(new_plan)} remaining steps")
        return {
            "plan": new_plan
        }

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
    Create plan-and-execute graph following LangGraph tutorial pattern.

    Flow:
    START -> plan -> agent -> replan -> [continue?]
                        ↑________________|
                                         |
                                       END

    - plan: Generate initial plan (list of steps)
    - agent: Execute current step with tools
    - replan: Review progress, update plan or respond
    - Loop until task is complete
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("replan", replan_node)

    # Define edges
    workflow.add_edge(START, "plan")       # Start with planning
    workflow.add_edge("plan", "agent")     # Plan -> Execute first step
    workflow.add_edge("agent", "replan")   # After execution -> Replan

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

logger.info("Plan-and-execute graph created (tutorial pattern)")
