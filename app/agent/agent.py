
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
from app.agent.types import AgentState
from app.agent.chat import chat_node, get_tools_from_config
from app.agent.utils import get_a2a_agents_from_assistant

from app.agent.deepagents_subgraph import deepagents_node
from langgraph.prebuilt import ToolNode
from langchain.messages import AIMessage, ToolMessage
from typing import cast
import json
import logging

logger = logging.getLogger(__name__)

async def async_tool_node(state: AgentState, config: RunnableConfig):

    selected_tools = state.get("selectedTools", None)
    assistant = state.get("assistant", None)

    # Get MCP config from state (populated by Next.js middleware)
    mcp_config = state.get("mcpConfig", None)
    # Extract A2A agents from assistant config
    a2a_agents = get_a2a_agents_from_assistant(assistant)
    
    user_id = state.get("user_id", None)

    tools = await get_tools_from_config(
        mcp_config=mcp_config,
        selected_tools=selected_tools,
        a2a_agents=a2a_agents,
        user_id=user_id
    )
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

    # All tools (including A2A) use standard ToolNode
    tool_node = ToolNode(tools)
    result = await tool_node.ainvoke(state, config)

    # Clear approval response
    state["approval_response"] = None

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
            logger.info(f"[interrupt_node] approval_response: {approval_response}")
           
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
                        logger.info(f"[interrupt_node] User denied tool execution or cancelled")
                        state["approval_response"] = approval_response
                   else:
                        logger.info(f"[interrupt_node] User approved tool execution")
                        # Store approval response for tool to access connection data
                        state["approval_response"] = approval_response

    return state

async def begin_node(state: AgentState, config: RunnableConfig):
    """Decide whether to use deepagents or existing agent based on plan_mode."""
    # Just pass through state, routing happens in conditional edge
    return state

async def route_begin(state: AgentState, config: RunnableConfig):
    """Route from begin_node to either deepagents or chat_node."""
    assistant = state.get("assistant", None)
    assistant_config = assistant.get("config", {}) if assistant else {}
    
    if state.get("plan_mode") or assistant_config.get("plan_mode"):
        logger.info("[route_begin] Routing to deepagents_subgraph")
        return "deepagents_node"
    
    logger.info("[route_begin] Routing to chat_node")
    return "chat_node"

async def route(state: AgentState, config: RunnableConfig):
    """Route after the chat node based on tool calls and assistant settings."""
    messages = state.get("messages", [])

    if messages and isinstance(messages[-1], AIMessage):
        ai_message = messages[-1]

        tool_calls = getattr(ai_message, "tool_calls", None) or getattr(
            ai_message, "additional_kwargs", {}
        ).get("tool_calls")

        if tool_calls:
            # Check if the tool being called is initiate_connection
            tool_name = tool_calls[0].get("name") if tool_calls else None

            # Always interrupt for initiate_connection
            if tool_name == "initiate_connection":
                logger.info(f"[route] Interrupting for initiate_connection tool call")
                return "interrupt_node"

            assistant = state.get("assistant", None)
            assistant_config = assistant.get("config", {}) if assistant else {}

            if assistant_config.get("ask_mode"):
                logger.info(f"[route] Routing to interrupt_node for ask_mode")
                return "interrupt_node"

            return "tools"

    return END

# build the graph
graph_builder = StateGraph(AgentState)

# nodes
graph_builder.add_node("begin_node", begin_node)
graph_builder.add_node("deepagents_node", deepagents_node)
graph_builder.add_node("chat_node", chat_node)
graph_builder.add_node("tools", async_tool_node)
graph_builder.add_node("interrupt_node", interrupt_node)

# edges from START
graph_builder.add_edge(START, "begin_node")

# conditional routing from begin_node
graph_builder.add_conditional_edges(
    "begin_node",
    route_begin,
    ["deepagents_node", "chat_node"]
)

# deepagents goes directly to END
graph_builder.add_edge("deepagents_node", END)

# existing chat_node edges
graph_builder.add_edge("interrupt_node", "tools")
graph_builder.add_edge("tools", "chat_node")

# conditional edges from chat_node
graph_builder.add_conditional_edges(
    "chat_node",
    route,
    ["tools", "interrupt_node", END]
)

graph = graph_builder.compile(
    checkpointer=MemorySaver(),
)