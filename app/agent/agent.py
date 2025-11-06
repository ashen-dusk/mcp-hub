
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

    # Get current tool call info
    ai_message = cast(AIMessage, messages[-1]) if messages and isinstance(messages[-1], AIMessage) else None
    tool_call = ai_message.tool_calls[0] if ai_message and ai_message.tool_calls else {}
    tool_name = tool_call.get("name", "unknown tool")
    tool_args = tool_call.get("args", {})

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
                "approval_response": None,
                "current_tool_call": None  # Clear tool call state
            }

        # User approved - continue with tool execution
        state["approval_response"] = None

    # Update state to show tool is executing
    # state["current_tool_call"] = {
    #     "name": tool_name,
    #     "args": tool_args,
    #     "status": "executing"
    # }

    tool_node = ToolNode(tools)
    result = await tool_node.ainvoke(state, config)

    # Update state to show tool execution complete
    result["current_tool_call"] = {
        "name": tool_name,
        "args": tool_args,
        "status": "complete",
        "result": result.get("messages", [])[-1].content if result.get("messages") else None
    }

    return result


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

                # Convert JSON string to dict if needed
                if isinstance(approval_response, str):
                    try:
                       approval_response = json.loads(approval_response)
                    except json.JSONDecodeError:
                       approval_response = {}

                if isinstance(approval_response, dict):
                   approved = approval_response.get("approved", False)
                   action = approval_response.get("action", "").upper()
                   # Get current tool call info
            
                   if not approved or action == "CANCEL":
                        print("User denied tool execution or cancelled.")

                        state["approval_response"] = approval_response
                   else:   
                        state["current_tool_call"] = {
                            "name": tool_call.get("name"),
                            "args": tool_call.get("args"),
                            "status": "executing"
                        }

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
# conditional edges
graph_builder.add_conditional_edges(
    "chat_node",
    route,
    ["tools", "interrupt_node", END]
)

graph = graph_builder.compile(
    checkpointer=MemorySaver(),
)