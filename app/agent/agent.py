"""
Simple tool-calling agent for testing with Tavily search and datetime tools.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
import json
from datetime import datetime, timezone
from app.agent.types import AgentState
from app.agent.chat import chat_node, get_tools
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage

# async def async_tool_node(state: AgentState, config: RunnableConfig):
#     sessionId = state.get("sessionId", None)
#     await copilotkit_emit_state(config, state)
#     tools = await get_tools(sessionId=sessionId)
#     print(f"DEBUG: async_tool_node: {tools}")
#     return ToolNode(tools)

async def async_tool_node(state: AgentState, config: RunnableConfig):
    # No interrupt logic here; handled in route() before transitioning.
    sessionId = state.get("sessionId", None)
    tools = await get_tools(sessionId=sessionId)
    print(f"DEBUG: async_tool_node: {tools}")

    tool_node = ToolNode(tools)
    tool_result = await tool_node.ainvoke(state, config)

    tool_results = []
    for message in tool_result.get("messages", []):
        if message.type == "tool":
            # Try to parse as JSON, otherwise use raw content
            try:
                result_content = json.loads(message.content)
            except (json.JSONDecodeError, TypeError):
                result_content = message.content

            tool_results.append({
                "tool_call_id": message.tool_call_id,
                "name": message.name,
                "result": result_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    state.update(tool_result)
    state["tool_calls"] = tool_results

    return state

async def handle_interrupt_node(state: AgentState, config: RunnableConfig):
    """Node to handle human-in-the-loop approval for tool execution."""
    messages = state.get("messages", [])
    ai_message = messages[-1]

    # Extract tool calls
    tool_calls = getattr(ai_message, "tool_calls", None) or getattr(
        ai_message, "additional_kwargs", {}
    ).get("tool_calls")

    tool_call = tool_calls[0]
    tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)

    print(f"DEBUG: Interrupting for approval of tool '{tool_name}'")

    # Interrupt to ask for approval
    approval = interrupt({
        "type": "approval",
        "content": f"Approve execution of tool '{tool_name}'?"
    })

    print(f"DEBUG: approval response: {approval}")

    # Handle rejection or skip
    if approval is False or (
        isinstance(approval, str) and approval.strip().upper() in ("REJECT", "NO", "SKIP")
    ):
        # Create ToolMessage for each skipped tool call
        skip_messages = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)

            skip_messages.append(
                ToolMessage(
                    content=f"Tool '{tool_name}' execution was skipped by user.",
                    tool_call_id=tool_call_id,
                )
            )

        return {"messages": skip_messages}

    # If approved, return state unchanged (will route to tools)
    return state

async def route(state: AgentState, config: RunnableConfig):
    """Route after the chat node, with optional human-in-the-loop approval before tools."""
    messages = state.get("messages", [])
    print(f"Routing based on last message: {messages[-1] if messages else 'No messages'}")
    print(f"Current state messages: {messages}")

    if messages and isinstance(messages[-1], AIMessage):
        ai_message = messages[-1]

        # Extract tool call info safely
        tool_calls = getattr(ai_message, "tool_calls", None) or getattr(
            ai_message, "additional_kwargs", {}
        ).get("tool_calls")

        if tool_calls:
            tool_call = tool_calls[0]
            tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            print(f"DEBUG: tool_name: {tool_name}, tool_call_id: {tool_call_id}")

            # Check if human-in-the-loop approval is enabled
            assistant = state.get("assistant", None)
            assistant_config = assistant.get("config", {}) if assistant else {}

            if assistant_config.get("ask_mode"):
                return "handle_interrupt"

            return "tools"

    return END

# build the graph
graph_builder = StateGraph(AgentState)

# nodes
graph_builder.add_node("chat_node", chat_node)
graph_builder.add_node("tools", async_tool_node)
graph_builder.add_node("handle_interrupt", handle_interrupt_node)

# edges
graph_builder.add_edge(START, "chat_node")
graph_builder.add_conditional_edges(
    "chat_node",
    route,
    {
        "tools": "tools",
        "handle_interrupt": "handle_interrupt",
        END: END
    }
)
graph_builder.add_edge("tools", "chat_node")
graph_builder.add_conditional_edges(
    "handle_interrupt",
    lambda state: "chat_node" if state["messages"] and isinstance(state["messages"][-1], ToolMessage) else "tools",
    {
        "tools": "tools",
        "chat_node": "chat_node"
    }
)

# compile the graph
graph = graph_builder.compile(
    checkpointer=MemorySaver(),
)