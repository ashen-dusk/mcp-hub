
import os
import logging
import platform
from typing import Optional, List, Any, cast
from datetime import datetime, timezone, timedelta

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.agent.types import AgentState
from app.agent.model import get_llm
from app.agent.utils import get_a2a_agents_from_assistant, create_a2a_system_prompt
from app.a2a.client import send_a2a_message
from app.mcp.utils import fetch_mcp_config_from_sessions

logger = logging.getLogger(__name__)

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


@tool
async def send_message_to_a2a_agent(task: str, agentUrl: str, agentName: str) -> str:
    """
    Sends a task to an A2A agent. Please specify the agent URL and agent name.
    
    Args:
        task: The comprehensive conversation-context summary and goal to be achieved regarding the user inquiry.
        agentUrl: The URL of the A2A agent to communicate with (e.g., http://localhost:9001)
        agentName: The name of the A2A agent (e.g., "Analysis Agent")

    Returns:
        Response from the A2A agent
    """

    try:
        if not task:
            raise ValueError("Missing required parameter: task")
        
        if not agentUrl and not agentName:
            raise ValueError("Must provide either agentUrl or agentName")

        # Use the URL directly if provided, otherwise we'll need to look it up
        url_to_use = agentUrl
        
        if not url_to_use:
            # agentName was provided, return error asking for URL
            raise ValueError(f"Agent name '{agentName}' provided but URL is required. Please use agentUrl parameter with the agent's URL.")

        logger.info(f"Delegating to A2A agent at {url_to_use}")
        logger.info(f"Task: {task}")

        # Send message to A2A agent using official a2a library
        response = await send_a2a_message(agent_url=url_to_use, message=task)

        logger.info(f"Received response from A2A agent at {url_to_use}")
        return response

    except Exception as e:
        error_msg = f"Error communicating with A2A agent: {str(e)}"
        logger.error(error_msg)
        return error_msg


async def get_tools_from_config(
    mcp_config: Optional[dict] = None,
    selected_tools: Optional[List[str]] = None,
    a2a_agents: Optional[List[dict]] = None
) -> List[Any]:
    """
    Get tools from MCP config and A2A agents.

    Args:
        mcp_config: MCP server configuration
        selected_tools: List of tool names to filter
        a2a_agents: List of A2A agents to enable delegation tool

    Returns:
        List of tool functions
    """
    tools_list = [get_system_info]

    # Add A2A tool if agents are available
    if a2a_agents and len(a2a_agents) > 0:
        tools_list.append(send_message_to_a2a_agent)
        logging.info(f"Added A2A delegation tool for {len(a2a_agents)} agents")

    if not mcp_config:
        logging.info("No MCP config provided, returning system tools only")
        return tools_list

    try:
        client = MultiServerMCPClient(mcp_config)

        # ✅ MUST await this
        mcp_tools = await client.get_tools()

        if selected_tools:
            mcp_tools = [
                tool for tool in mcp_tools
                if getattr(tool, 'name', '') in selected_tools
            ]
            logging.info(f"Filtered to {len(mcp_tools)} selected tools")

        if mcp_tools:
            tools_list.extend(mcp_tools)
            logging.info(f"Loaded {len(mcp_tools)} MCP tools from config")

    except Exception as e:
        logging.exception(f"Error loading MCP tools from config: {e}")

    return tools_list



async def chat_node(state: AgentState, config: RunnableConfig):
    """Handle chat operations and determine next actions"""
    sessionId = state.get("sessionId", None)
    assistant = state.get("assistant", None)
    selected_tools = state.get("selectedTools", None)
    mcp_sessions = state.get("mcpSessions", None)

    # Fetch MCP config using server-specific sessionIds
    mcp_config = await fetch_mcp_config_from_sessions(mcp_sessions)

    if mcp_config:
        logging.info(f"[chat_node] Using config with {len(mcp_config)} servers")
    else:
        logging.info(f"[chat_node] No MCP config available")

    # Extract A2A agents from assistant config
    a2a_agents = get_a2a_agents_from_assistant(assistant)

    logging.info(f"[chat_node] sessionId: {sessionId}")
    logging.info(f"[chat_node] mcp_sessions: {mcp_sessions}")
    logging.info(f"[chat_node] selectedTools: {selected_tools}")
    logging.info(f"[chat_node] a2a_agents: {a2a_agents}")

    # Clear previous tool call state when processing a new user message
    # (not when returning from tool execution)
    messages = state.get("messages", [])
    if messages and isinstance(messages[-1], HumanMessage):
        state["current_tool_call"] = None

    # Get tools from MCP config and A2A agents
    tools = await get_tools_from_config(
        mcp_config=mcp_config,
        selected_tools=selected_tools,
        a2a_agents=a2a_agents
    )
    # === Extract config values from assistant ===
    assistant_config = assistant.get("config", {}) if assistant else {}
    datetime_context = assistant_config.get("datetime_context", False)

    # === Bind LLM with tools (temperature and max_tokens are extracted inside get_llm) ===
    llm = get_llm(state)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

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

    # Use A2A system prompt if A2A agents are available
    if a2a_agents and len(a2a_agents) > 0:
        # Get assistant instructions to pass to A2A system prompt
        assistant_instructions = assistant.get("instructions") if assistant else None
        system_message = create_a2a_system_prompt(a2a_agents, assistant_instructions)
    else:
        # Use standard system message for non-A2A assistants
        if assistant and assistant.get("instructions"):
            system_message = f"""{base_system_message}

# Custom Assistant Instructions
{assistant.get("instructions")}

Follow the custom instructions above while helping the user.
"""
        else:
            system_message = base_system_message

    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=system_message),
            *state["messages"]
        ],
        config=config,
    )
    logging.info(f"[chat_node] LLM response received")

    tool_calls = getattr(response, "tool_calls", [])
    logging.info(f"[chat_node] Tool calls: {tool_calls}")

    if tool_calls:
        tool_call = tool_calls[0]
        logging.info(f"[chat_node] First tool call: {tool_call.get('name')}")
        # Only track A2A agent tool calls for approval workflow
        if tool_call.get("name") == "send_message_to_a2a_agent":
            state["current_tool_call"] = {
                "name": tool_call.get("name"),
                "args": tool_call.get("args"),
                "status": "executing"
            }
            
    return {
        **state,
        "messages": [*state["messages"], response],
    }
