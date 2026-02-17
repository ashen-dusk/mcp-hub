from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from app.agent.types import AgentState
from app.agent.chat import chat_node, get_tools
from langgraph.prebuilt import ToolNode
from langchain.messages import AIMessage
import logging

logger = logging.getLogger(__name__)

# Define routing logic
def route(state: AgentState):
    """Route after the chat node based on tool calls."""
    messages = state.get("messages", [])
    if messages and isinstance(messages[-1], AIMessage):
        ai_message = messages[-1]
        if ai_message.tool_calls:
            return "tools"
    return END

# build the graph
graph_builder = StateGraph(AgentState)

# nodes
graph_builder.add_node("chat_node", chat_node)

# Define tools for ToolNode
tools = get_tools()
graph_builder.add_node("tools", ToolNode(tools))

# edges
graph_builder.add_edge(START, "chat_node")
graph_builder.add_edge("tools", "chat_node")

# conditional edges from chat_node
graph_builder.add_conditional_edges(
    "chat_node",
    route,
    ["tools", END]
)

graph = graph_builder.compile(
    checkpointer=MemorySaver(),
)