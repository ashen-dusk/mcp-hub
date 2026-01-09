
import os
import logging
from typing import Optional, List, Any, cast
from datetime import datetime, timezone, timedelta

from langchain.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.agent.types import AgentState
from app.agent.model import get_llm
from app.agent.utils import get_a2a_agents_from_assistant, create_a2a_system_prompt

from app.mcp.models import MCPServer
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

User = get_user_model()

from app.agent.tools import (
    get_current_datetime,
    search_web,
    get_system_info,
    send_message_to_a2a_agent,
    add_mcp_server,
    delete_mcp_server,
    list_mcp_servers,
    search_servers,
    check_connections,
    initiate_connection
)

logger = logging.getLogger(__name__)


async def get_tools_from_config(
    mcp_config: Optional[dict] = None,
    selected_tools: Optional[List[str]] = None,
    a2a_agents: Optional[List[dict]] = None,
    user_id: Optional[int] = None
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
    # initialize tools
    tools_list = []

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
    user_id = state.get("user_id", None)

    # === Initialize tools ===
    internal_tools = [search_servers, check_connections, initiate_connection]

    # Get MCP config from state (populated by Next.js middleware)
    mcp_config = state.get("mcpConfig", None)
    # Extract A2A agents from assistant config
    a2a_agents = get_a2a_agents_from_assistant(assistant)

    logging.info(f"[chat_node] sessionId: {sessionId}")
    logging.info(f"[chat_node] mcp_config: {mcp_config}")
    logging.info(f"[chat_node] selectedTools: {selected_tools}")
    logging.info(f"[chat_node] a2a_agents: {a2a_agents}")

    # Clear previous tool call state when processing a new user message
    # (not when returning from tool execution)
    messages = state.get("messages", [])
    if messages and isinstance(messages[-1], HumanMessage):
        state["current_tool_call"] = None

    tools = [
        # MCP and A2A tools
        *await get_tools_from_config(
            mcp_config=mcp_config,
            selected_tools=selected_tools,
            a2a_agents=a2a_agents,
            user_id=user_id,
        ),
        # Internal tools
        *internal_tools,
    ]
    # === Extract config values from assistant ===
    assistant_config = assistant.get("config", {}) if assistant else {}
    datetime_context = assistant_config.get("datetime_context", False)

    # === Bind LLM with tools (temperature and max_tokens are extracted inside get_llm) ===
    llm = get_llm(state)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    # === Build system message with conditional datetime ===
    base_system_message = """
    You are MCP Assistant, an AI assistant that helps users connect to and use Model Context Protocol (MCP) servers to complete their tasks and answer queries.

    # Your Workflow

    When a user asks for help with a task:

    1. **Check Active Connections First**
       - Use the `check_connections` tool to see if the user already has any active MCP server connections
       - If you find an active connection with the tools needed for the task, use it directly

    2. **Search for Required MCP Servers** (if no suitable active connection exists)
       - Use the `search_servers` tool to find public MCP servers that can help with the user's task
       - Search using relevant keywords from the user's request (e.g., "github" for GitHub tasks, "slack" for Slack tasks)
       - Review the search results and identify the most appropriate server(s) for the task

    3. **Initiate Connection** (if you find a suitable server)
       - Use the `initiate_connection` tool to connect to the MCP server
       - Required parameters: server_url, server_name (use the server's URL and a server name)
       - The user will be prompted to approve the connection before it proceeds
       - Wait for the connection to complete successfully

    4. **Complete the Task**
       - Once connected, the MCP server's tools will be available to you
       - Use the appropriate tools to complete the user's original request
       - Provide clear feedback about what you're doing

    # Error Handling

    - If no MCP servers are found for a task: Clearly explain that you couldn't find a suitable MCP server for this specific task and suggest alternative approaches or ask the user if they know of a specific MCP server to use
    - If connection fails: Explain the error clearly and suggest next steps (e.g., check server URL, check OAuth credentials)
    - If a tool call fails: Don't give vague responses - explain what went wrong and what the user can do about it
    - Never say "I don't have access to that" without first checking for connections and searching for available MCP servers

    # Important Notes

    - Always be transparent about what you're doing (checking connections, searching servers, initiating connections)
    - If you're unsure which MCP server to use, present options to the user and let them choose
    - MCP servers may require OAuth authentication - guide users through this process when needed
    - Be helpful, professional, and clear in your communication
    """

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
            system_message = f"""
            {base_system_message}

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

    print(f"[chat_node] LLM response: {response}")
    # logging.info(f"[chat_node] LLM response: {response}")
    logging.info(f"[chat_node] LLM response received")
 
    return {
        **state,
        "messages": [*state["messages"], response],
        # "reasoning_content": thinking_text,
    }
