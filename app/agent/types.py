from typing import Any, Optional, Dict, List
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class AgentState(MessagesState):
    """Conversation state for the agent."""

    # Original fields
    model: str
    status: Optional[str] = None
    sessionId: Optional[str] = None
    tool_calls: Optional[Any] = None
    assistant: Optional[Dict[str, Any]] = None
    approval_response: Optional[Dict[str, Any]] = None
    current_tool_call: Optional[Dict[str, Any]] = None

    # MCP session IDs for fetching server configs from Next.js
    mcpSessions: Optional[List[str]] = None
    # Selected tool names to filter
    selectedTools: Optional[List[str]] = None
    # LLM provider configuration
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
