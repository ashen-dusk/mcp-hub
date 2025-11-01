
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
from app.agent.types import AgentState
from app.agent.chat import chat_node, get_tools
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage
from typing import cast
import json

async def async_tool_node(state: AgentState, config: RunnableConfig):
    sessionId = state.get("sessionId", None)
    tools = await get_tools(sessionId=sessionId)
    messages = state.get("messages", [])

    # Check if we have an approval response from the interrupt
    approval_response = state.get("approval_response")
    if approval_response:
        # Parse JSON string if needed
        if isinstance(approval_response, str):
            try:
                approval_response = json.loads(approval_response)
            except json.JSONDecodeError:
                approval_response = {}

        # Check if user cancelled
        if not approval_response.get("approved", False) or approval_response.get("action") == "CANCEL":
            ai_message = cast(AIMessage, messages[-1])
            tool_call = ai_message.tool_calls[0] if ai_message.tool_calls else {}
            tool_name = tool_call.get("name", "unknown tool")
            tool_call_id = tool_call.get("id", "")

            # Must send ToolMessage to satisfy OpenAI's requirement
            cancel_msg = ToolMessage(
                content=f"Tool execution cancelled by user.",
                tool_call_id=tool_call_id,
                name=tool_name
            )
            return {
                **state,
                "messages": [*messages, cancel_msg],
                "approval_response": None  # Clear the approval response
            }

        # User approved - continue with tool execution
        state["approval_response"] = None  # Clear the approval response

    tool_node = ToolNode(tools)
    return await tool_node.ainvoke(state, config)


async def interrupt_node(state: AgentState, config: RunnableConfig):
    """
    Interrupt node that pauses execution to ask for user approval.
    Uses the interrupt() function to send tool call info to the client.
    """
    messages = state.get("messages", [])

    if messages and isinstance(messages[-1], AIMessage):
        ai_message = cast(AIMessage, messages[-1])
        tool_calls = getattr(ai_message, "tool_calls", [])

        if tool_calls:
            tool_call = tool_calls[0]

            # Use interrupt() to pause and send data to client
            # The client can resume with approval/denial
            approval_response = interrupt({
                "type": "tool_approval_request",
                "tool_name": tool_call.get("name"),
                "tool_args": tool_call.get("args"),
                "tool_id": tool_call.get("id"),
                "message": f"Do you want to execute {tool_call.get('name')}?"
            })

            # Store the approval response in state for async_tool_node to use
            if approval_response:
                state["approval_response"] = approval_response

    return state

async def route(state: AgentState, config: RunnableConfig):
    """Route after the chat node based on tool calls assistant settings."""
    messages = state.get("messages", [])

    if messages and isinstance(messages[-1], AIMessage):
        ai_message = messages[-1]

        tool_calls = getattr(ai_message, "tool_calls", None) or getattr(
            ai_message, "additional_kwargs", {}
        ).get("tool_calls")

        if tool_calls:
            assistant = state.get("assistant", None)
            assistant_config = assistant.get("config", {}) if assistant else {}

            if assistant_config.get("ask_mode"):
                return "interrupt_node"

            return "tools"

    return END

# build the graph
graph_builder = StateGraph(AgentState)

# nodes
graph_builder.add_node("chat_node", chat_node)
graph_builder.add_node("tools", async_tool_node)
graph_builder.add_node("interrupt_node", interrupt_node)
# edges
graph_builder.add_edge(START, "chat_node")
graph_builder.add_edge("interrupt_node", "tools")
graph_builder.add_edge("tools", "chat_node")

graph_builder.add_conditional_edges(
    "chat_node",
    route,
    ["tools", "interrupt_node", END]
)

graph = graph_builder.compile(
    checkpointer=MemorySaver(),
    # interrupt_after=['interrupt_node']  # No longer needed - using interrupt() function instead
)