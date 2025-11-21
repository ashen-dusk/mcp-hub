
import os
import logging
from typing import Optional, AsyncIterator
from datetime import datetime, timezone, timedelta

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from langchain_core.callbacks.base import AsyncCallbackHandler

from app.agent.types import AgentState
from app.agent.model import get_llm
from app.mcp.manager import mcp
import platform


class ThinkingCallbackHandler(AsyncCallbackHandler):
    """Callback handler to capture and emit thinking/reasoning blocks during streaming."""

    def __init__(self):
        self.thinking_content = []

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        """Called when a new token is generated."""
        # Check if this token is part of a thinking block
        # Claude models with extended_thinking will have thinking blocks
        # in the format: <thinking>...</thinking>
        pass

    async def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        """Called when LLM starts."""
        self.thinking_content = []

    async def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM ends."""
        # Extract thinking blocks from response if present
        if hasattr(response, 'generations') and response.generations:
            for generation in response.generations:
                for gen in generation:
                    if hasattr(gen, 'message') and hasattr(gen.message, 'additional_kwargs'):
                        thinking = gen.message.additional_kwargs.get('thinking')
                        if thinking:
                            self.thinking_content.append(thinking)

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

    # Clear previous tool call state when processing a new user message
    # (not when returning from tool execution)
    messages = state.get("messages", [])
    if messages and isinstance(messages[-1], HumanMessage):
        state["current_tool_call"] = None

    tools = await get_tools(sessionId=sessionId)
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

    # Add assistant-specific instructions
    if assistant and assistant.get("instructions"):
        system_message = f"""{base_system_message}

        # Custom Assistant Instructions
        {assistant.get("instructions")}

        Follow the custom instructions above while helping the user.
        """
    else:
        system_message = base_system_message

    # Create callback handler for thinking
    thinking_handler = ThinkingCallbackHandler()

    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=system_message),
            *state["messages"]
        ],
        config=config,
    )

    # Extract thinking blocks from Claude's extended thinking
    thinking_blocks = []
    if hasattr(response, 'content') and isinstance(response.content, list):
        for content_block in response.content:
            if isinstance(content_block, dict):
                # Check for thinking block in Claude's response
                if content_block.get('type') == 'thinking':
                    thinking_blocks.append(content_block.get('thinking', ''))

    # Store thinking blocks in the response for streaming
    if thinking_blocks:
        print(f"💭 Captured {len(thinking_blocks)} thinking blocks")
        if not hasattr(response, 'additional_kwargs'):
            response.additional_kwargs = {}
        response.additional_kwargs['thinking_blocks'] = thinking_blocks

    print(response, "response in chat_node")
    return {
        **state,
        "messages": [*state["messages"], response],
    }
