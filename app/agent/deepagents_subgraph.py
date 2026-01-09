import logging
from typing import Any, List, Optional
from langchain_core.runnables import RunnableConfig
from deepagents import create_deep_agent

from app.agent.types import AgentState
from app.agent.chat import get_tools
from app.agent.model import get_llm
from app.agent.utils import get_a2a_agents_from_assistant


logger = logging.getLogger(__name__)

async def deepagents_node(state: AgentState, config: RunnableConfig):
    """
    Deep agent subgraph for complex planning tasks.
    
    This node is invoked when plan_mode is enabled in the assistant config.
    It uses the deepagents library to provide planning tools, filesystem access,
    and task decomposition capabilities.
    """
        
    # Extract state data
    sessionId = state.get("sessionId", None)
    assistant = state.get("assistant", None)
    selected_tools = state.get("selectedTools", None)
    
    # Get MCP config from state (populated by Next.js middleware)
    mcp_config = state.get("mcpConfig", None)
    # Extract A2A agents from assistant config
    a2a_agents = get_a2a_agents_from_assistant(assistant)
    
    # Get tools from MCP config and A2A agents
    tools = await get_tools(
        mcp_config=mcp_config,
        selected_tools=selected_tools,
        a2a_agents=a2a_agents
    )
        
    # Get LLM from state (respects assistant's model/temperature config)
    llm = get_llm(state)
    
    # System prompt for deep agent
    base_system_prompt = """You are an expert researcher. Your job is to conduct \
thorough research and provide accurate and detailed information. Note: Don't forget to mark a todo as completed if a step is completed."""
    
    # Add assistant instructions if available
    if assistant and assistant.get("instructions"):
        system_prompt = f"""{base_system_prompt}

# Custom Assistant Instructions
{assistant.get("instructions")}

Follow the custom instructions above while helping the user."""
    else:
        system_prompt = base_system_prompt
        
    # Create deep agent
    deep_agent = create_deep_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt
    )
    
    logger.info("[deepagents_node] Invoking deep agent")
    
    # Invoke deep agent with the current state
    result = await deep_agent.ainvoke(state, config)
  
    return {
        **state,
        "messages": result.get("messages", state.get("messages", [])),
        "plan_mode": True  # Indicate that plan mode is active
    }
