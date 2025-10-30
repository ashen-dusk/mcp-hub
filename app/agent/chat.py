
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
    sessionId = state.get("sessionId", None)
    assistant = state.get("assistant", None)
    print('chat_node: sessionId in chat_node', sessionId)
    print(state, 'state in chat_node')
    tools = await get_tools(sessionId=sessionId)

    # === Extract config values from assistant ===
    assistant_config = assistant.get("config", {}) if assistant else {}
    temperature = assistant_config.get("temperature", 0)  # default 0
    max_tokens = assistant_config.get("max_tokens")  # can be None
    datetime_context = assistant_config.get("datetime_context", False)

    # === Bind LLM with dynamic temperature ===
    llm = get_llm(state)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False).with_config(
        {"temperature": temperature}
    )

    # === Build system message with conditional datetime ===
    base_system_message = "You are a helpful assistant named MCP Assistant that can answer questions and perform tasks using the MCP servers."

    if datetime_context:
        ist_timezone = timezone(timedelta(hours=5, minutes=30))
        ist_now = datetime.now(ist_timezone)
        datetime_str = f"""
        Today's date: {ist_now.strftime("%Y-%m-%d")}
        Current time (IST): {ist_now.strftime("%H:%M:%S")}
        """
        base_system_message = datetime_str.strip() + "\n\n" + base_system_message

    # Add assistant-specific instructions
    if assistant and assistant.get("instructions"):
        system_message = f"""{base_system_message}

        # Custom Assistant Instructions
        {assistant.get("instructions")}
        
        Follow the custom instructions above while helping the user.
        """
    else:
        system_message = base_system_message

    # === Prepare invocation config with max_tokens if available ===
    invocation_config = {}
    if max_tokens is not None:
        invocation_config["max_tokens"] = max_tokens

    # Merge with original config (preserve callbacks, etc.)
    final_config = {**config, **invocation_config}

    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=system_message),
            *state["messages"]
        ],
        config=final_config,
    )
    print(response, "response in chat_node")
    return {
        **state,
        "messages": [*state["messages"], response],
    }
