from typing import Any, Optional, Dict, List
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class AgentState(MessagesState):
    """Conversation state for the agent."""

    # Original fields
    model: str
    status: Optional[str] = None
    reasoning_content: Optional[str] = None
    sessionId: Optional[str] = None
    tool_calls: Optional[Any] = None
    assistant: Optional[Dict[str, Any]] = None
    approval_response: Optional[Dict[str, Any]] = None

    # MCP server configuration (populated by Next.js middleware)
    mcpConfig: Optional[Dict[str, Any]] = None
    # LLM configuration (llm_provider, llm_api_key)
    llm_config: Optional[Dict[str, Any]] = None
    
    # Selected tool names to filter
    selectedTools: Optional[List[str]] = None
    # LLM provider configuration
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    plan_mode: Optional[bool] = None
    
    # Deepagents todo list for plan mode
    todos: Optional[List[Dict[str, Any]]] = None
    
    # Authenticated user ID for ownership checks
    user_id: Optional[int] = None
