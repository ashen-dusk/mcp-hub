from typing import Any, Optional, Dict
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    """Conversation state for the simple tool-calling agent."""

    model: str
    status: Optional[str] = None
    sessionId: Optional[str] = None
    tool_calls: Optional[Any] = None
    assistant: Optional[Dict[str, Any]] = None