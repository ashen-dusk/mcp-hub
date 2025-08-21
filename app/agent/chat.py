
import json
import os
from datetime import datetime
import asyncio
import logging
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_core.tools import tool

from app.agent.types import AgentState
from app.agent.model import get_llm
from langgraph.graph import END
from langgraph.types import Command
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from app.mcp.manager import mcp

@tool
def get_current_datetime() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is not set.")
    search = TavilySearch(max_results=3)
    return search.invoke(query)

async def get_tools():
    await mcp.initialize_client()
    tools_list = [get_current_datetime]
    # get tools from MCP manager
    try:
        mcp_tools = mcp.get_tools()
        if mcp_tools:
            tools_list.extend(mcp_tools)
    except Exception as e:
        logging.exception(f"Error fetching MCP tools: {e}")

    return tools_list

async def chat_node(state: AgentState, config: RunnableConfig):
    """Handle chat operations and determine next actions"""
    tools = await get_tools()
    print(f"DEBUG: tools: {tools}")

    llm_with_tools = get_llm(state).bind_tools(tools, parallel_tool_calls=False)
        
    system_message = f"""
        You are a helpful assistant that can answer questions and perform tasks using the MCP servers.
        """
    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=system_message),
            *state["messages"]
        ],
        config=config,
        )
    print(response, "response in chat_node")
    return {
        **state,
        "messages": [*state["messages"], response],
    }
    
