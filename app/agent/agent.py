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
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode


# async def async_tool_node(state: AgentState, config: RunnableConfig):
#     sessionId = state.get("sessionId", None)
#     await copilotkit_emit_state(config, state)
#     tools = await get_tools(sessionId=sessionId)
#     print(f"DEBUG: async_tool_node: {tools}")
#     return ToolNode(tools)

async def async_tool_node(state: AgentState, config: RunnableConfig):
    sessionId = state.get("sessionId", None)
    tools = await get_tools(sessionId=sessionId)
    print(f"DEBUG: async_tool_node: {tools}")
    
    tool_node = ToolNode(tools)
    tool_result = await tool_node.ainvoke(state, config)

    tool_results = []
    for message in tool_result.get("messages", []):
        if message.type == "tool":
            tool_results.append({
                "tool_call_id": message.tool_call_id,
                "name": message.name,
                "result": json.loads(message.content),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    state.update(tool_result)
    state["tool_calls"] = tool_results

    return state

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