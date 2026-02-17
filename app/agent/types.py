from typing import Any, Optional, Dict, List
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class AgentState(MessagesState):
    """Conversation state for the simplified agent."""
    model: str
    llm_config: Optional[Dict[str, Any]] = None
    user_id: Optional[int] = None
