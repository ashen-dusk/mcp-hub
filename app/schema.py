from langgraph.graph import MessagesState
from typing import Optional

class AgentState(MessagesState):
    """Conversation state for the simple tool-calling agent."""
  
    model: Optional[str] = "openai"
    status: Optional[str] = None
        
