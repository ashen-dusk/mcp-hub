from typing import Any, Optional
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    """Conversation state for the simple tool-calling agent."""

    model: Optional[str] = "openai"
    status: Optional[str] = None
    sessionId: Optional[str] = None
    tool_calls: Optional[Any] = None