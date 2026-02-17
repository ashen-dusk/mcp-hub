from langchain.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.types import AgentState
from app.agent.model import get_llm
from app.agent.utils import get_a2a_agents_from_assistant, create_a2a_system_prompt

from app.mcp.models import MCPServer
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

User = get_user_model()

from app.agent.tools import (
    search_web,
    get_system_info,
)

logger = logging.getLogger(__name__)


def get_tools() -> List[Any]:
    """
    Get built-in tools only: tavily search and system info.
    """
    return [search_web, get_system_info]


async def chat_node(state: AgentState, config: RunnableConfig):
    """Handle chat operations with a casual tone and built-in tools."""
    
    # Get tools (now just built-in ones)
    tools = get_tools()
    
    # Get LLM
    llm = get_llm(state)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    # Casual system prompt
    system_message = """You are a helpful, casual assistant. 
    Act like a human, not an AI. 
    - Use a conversational, friendly tone.
    - Avoid robotic phrases like "As an AI language model" or "I can help with that".
    - Keep responses concise and direct, like a text message.
    - Use occasional emojis if appropriate, but don't overdo it.
    - If you don't know something, just say so naturally."""

    response = await llm_with_tools.ainvoke(
        [
            SystemMessage(content=system_message),
            *state["messages"]
        ],
        config=config,
    )

    logging.info(f"[chat_node] LLM response received")
 
    return {
        **state,
        "messages": [*state["messages"], response],
    }
