"""
Simple tool-calling agent for testing with Tavily search and datetime tools.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.schema import AgentState
from app.chat import chat_node, get_tools
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode


async def async_tool_node(state: AgentState, config: RunnableConfig):
    tools = await get_tools()
    print(f"DEBUG: async_tool_node: {tools}")
    return ToolNode(tools)

# build the graph
graph_builder = StateGraph(AgentState)

# nodes
graph_builder.add_node("chat_node", chat_node)
graph_builder.add_node("tools", async_tool_node)

# edges
graph_builder.add_edge(START, "chat_node")
graph_builder.add_conditional_edges(
    "chat_node",
    tools_condition,
    {
        "tools": "tools",
        END: END
    }
)
graph_builder.add_edge("tools", "chat_node")

# compile the graph
graph = graph_builder.compile(
    checkpointer=MemorySaver(),
)