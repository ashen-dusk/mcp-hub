"""
Enhanced Plan-and-Execute graph with reasoning capabilities.
This combines the strategic planning approach with visible reasoning.
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.types import AgentState
from app.agent.plan_and_execute import (
    plan_node,
    execute_step_node,
    tool_execution_node,
    replan_node,
    should_continue_execution,
    should_replan
)


async def reasoning_plan_node(state: AgentState, config):
    """
    Enhanced plan node that shows reasoning about the planning strategy.
    This makes the planning process visible to the user.
    """
    from app.agent.model import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    # Get the user's request
    messages = state.get("messages", [])
    last_user_msg = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg
            break

    if not last_user_msg:
        return await plan_node(state, config)

    # Generate reasoning about how to break down the task
    llm = get_llm(state)

    reasoning_prompt = f"""Before creating a plan, let me think about the best approach:

User's request: {last_user_msg.content}

Let me consider:
1. What is the overall goal?
2. What are the key steps required?
3. What dependencies exist between steps?
4. What tools or resources will be needed?
5. What potential challenges might arise?

My strategic thinking:"""

    reasoning_response = await llm.ainvoke([
        SystemMessage(content="You are a strategic planning assistant that thinks carefully before creating plans."),
        HumanMessage(content=reasoning_prompt)
    ])

    print(f"📋 Planning reasoning: {reasoning_response.content[:150]}...")

    # Store the planning reasoning
    if not state.get("planning_reasoning"):
        state["planning_reasoning"] = []

    state["planning_reasoning"].append({
        "type": "plan_reasoning",
        "content": reasoning_response.content,
        "timestamp": "now"
    })

    # Now proceed with actual planning
    return await plan_node(state, config)


async def reasoning_execute_step_node(state: AgentState, config):
    """
    Enhanced execute node that shows reasoning about how to execute the current step.
    """
    from app.agent.model import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    # Get current step
    plan_state = state.get("plan_state", {})
    steps = plan_state.get("steps", [])
    current_step_idx = plan_state.get("current_step_index", 0)

    if current_step_idx < len(steps):
        current_step = steps[current_step_idx]

        # Generate reasoning about executing this step
        llm = get_llm(state)

        execution_reasoning_prompt = f"""Before executing this step, let me think it through:

Step: {current_step.get('description', '')}

Let me consider:
1. What exactly needs to be done?
2. What tools should I use?
3. What information do I need?
4. How will I know if this step succeeds?
5. What could go wrong?

My execution strategy:"""

        reasoning_response = await llm.ainvoke([
            SystemMessage(content="You are a careful executor that thinks before acting."),
            HumanMessage(content=execution_reasoning_prompt)
        ])

        print(f"⚙️ Execution reasoning: {reasoning_response.content[:150]}...")

        # Store the execution reasoning
        if not state.get("execution_reasoning"):
            state["execution_reasoning"] = []

        state["execution_reasoning"].append({
            "type": "execution_reasoning",
            "step_number": current_step_idx + 1,
            "content": reasoning_response.content,
            "timestamp": "now"
        })

    # Now proceed with actual execution
    return await execute_step_node(state, config)


async def reasoning_replan_node(state: AgentState, config):
    """
    Enhanced replan node that shows reasoning about adapting the plan.
    """
    from app.agent.model import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    # Get plan state
    plan_state = state.get("plan_state", {})
    steps = plan_state.get("steps", [])

    # Generate reasoning about replanning
    llm = get_llm(state)

    replan_reasoning_prompt = f"""The plan needs to be adjusted. Let me think about this:

Current plan status:
- Completed steps: {sum(1 for s in steps if s.get('status') == 'completed')}
- Remaining steps: {sum(1 for s in steps if s.get('status') == 'pending')}
- Failed steps: {sum(1 for s in steps if s.get('status') == 'failed')}

Let me consider:
1. What went well?
2. What didn't work as expected?
3. What new information do we have?
4. How should we adjust the plan?
5. Are we still on track for the goal?

My replanning thoughts:"""

    reasoning_response = await llm.ainvoke([
        SystemMessage(content="You are an adaptive planner that learns from execution results."),
        HumanMessage(content=replan_reasoning_prompt)
    ])

    print(f"🔄 Replanning reasoning: {reasoning_response.content[:150]}...")

    # Store the replanning reasoning
    if not state.get("replanning_reasoning"):
        state["replanning_reasoning"] = []

    state["replanning_reasoning"].append({
        "type": "replanning_reasoning",
        "content": reasoning_response.content,
        "timestamp": "now"
    })

    # Now proceed with actual replanning
    return await replan_node(state, config)


# Build the reasoning-enhanced plan-and-execute graph
def create_reasoning_plan_execute_graph():
    """
    Create a plan-and-execute graph with reasoning at each stage.
    """
    graph_builder = StateGraph(AgentState)

    # Add nodes with reasoning
    graph_builder.add_node("plan", reasoning_plan_node)
    graph_builder.add_node("execute_step", reasoning_execute_step_node)
    graph_builder.add_node("tools", tool_execution_node)
    graph_builder.add_node("replan", reasoning_replan_node)

    # Add edges
    graph_builder.add_edge(START, "plan")
    graph_builder.add_conditional_edges(
        "plan",
        lambda state: "execute_step",
    )

    graph_builder.add_conditional_edges(
        "execute_step",
        should_continue_execution,
        {
            "tools": "tools",
            "continue": "replan",
            "end": END,
        }
    )

    graph_builder.add_edge("tools", "execute_step")

    graph_builder.add_conditional_edges(
        "replan",
        should_replan,
        {
            "continue": "execute_step",
            "end": END,
        }
    )

    # Compile with checkpointer
    checkpointer = MemorySaver()
    return graph_builder.compile(checkpointer=checkpointer)


# Export the graph
reasoning_plan_execute_graph = create_reasoning_plan_execute_graph()
