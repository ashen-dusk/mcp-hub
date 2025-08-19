
import json
import os
from datetime import datetime, timezone, timedelta
from typing import cast
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig
from copilotkit.langgraph import copilotkit_emit_state, copilotkit_emit_message

from app.schema import AgentState
from app.model import get_llm
from langgraph.graph import END
from langgraph.types import Command
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from .mcp_manager import mcp_manager

# define tools
@tool
def get_current_datetime() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment variables."
        )
    search = TavilySearch(max_results=3)
    return search.invoke(query)

async def get_tools():
    tools = [get_current_datetime]
    tools.extend(await mcp_manager.aget_langchain_tools())
    print(f"DEBUG: get_tools: {tools}")
    return tools
    
# ------------------------------------------------------------
# chat node

async def chat_node(state: AgentState, config: RunnableConfig):
    """Handle chat operations and determine next actions"""
    tools = await get_tools()

    llm_with_tools = get_llm(state).bind_tools(tools, parallel_tool_calls=False)
        
    system_message = f"""
        You are a helpful agent that can search the web for information.
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
    
