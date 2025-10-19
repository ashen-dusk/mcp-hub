
import os
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_core.tools import tool

from app.agent.types import AgentState
from app.agent.model import get_llm
from app.mcp.manager import mcp
import platform

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

@tool
def get_system_info() -> str:
    """Return basic information about the system environment."""
    return f"{platform.system()} {platform.release()} ({platform.processor()})"
    
async def get_tools(sessionId: Optional[str]=None):
    tools_list = [get_system_info]
    # sessionId = 'html78910'
    # get tools from MCP manager scoped to user/session
    try:
        mcp_tools = await mcp.aget_tools(session_id=sessionId)
        if mcp_tools:
            tools_list.extend(mcp_tools)
    except Exception as e:
        logging.exception(f"Error fetching scoped MCP tools: {e}")

    return tools_list

async def chat_node(state: AgentState, config: RunnableConfig):
    """Handle chat operations and determine next actions"""
    # sessionId = config["configurable"].get("copilotkit_auth")
    sessionId = state.get("sessionId", None)
    print('chat_node: sessionId in chat_node', sessionId)
    print(state, 'state in chat_node')
    tools = await get_tools(sessionId=sessionId)
    # user_id = state.get("user_id", None)
    # toolkit_names = state.get("toolkit", [])


    llm_with_tools = get_llm(state).bind_tools(tools, parallel_tool_calls=False)
        
        # Get IST time (UTC+5:30)
    ist_timezone = timezone(timedelta(hours=5, minutes=30))
    ist_now = datetime.now(ist_timezone)

    system_message = f"""
     Today's date: {ist_now.strftime("%Y-%m-%d")}
     Current time (IST): {ist_now.strftime("%H:%M:%S")}
        You are a helpful assistant named MCP Assistant that can answer questions and perform tasks using the MCP servers.
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
    
