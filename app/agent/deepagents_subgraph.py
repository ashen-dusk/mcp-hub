import logging
from typing import Any, List, Optional
from langchain_core.runnables import RunnableConfig
from deepagents import create_deep_agent

from app.agent.types import AgentState
from app.agent.chat import get_tools_from_config
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
    # logger.info("[deepagents_node] Starting deep agent execution")
    
    # Extract state data
    sessionId = state.get("sessionId", None)
    assistant = state.get("assistant", None)
    selected_tools = state.get("selectedTools", None)
    
    # Get MCP config from state (populated by Next.js middleware)
    mcp_config = state.get("mcpConfig", None)
    # Extract A2A agents from assistant config
    a2a_agents = get_a2a_agents_from_assistant(assistant)
    
    # logger.info(f"[deepagents_node] sessionId: {sessionId}")
    # logging.info(f"[deepagents_node] mcp_config: {mcp_config}")
    # logger.info(f"[deepagents_node] selectedTools: {selected_tools}")
    # logger.info(f"[deepagents_node] a2a_agents: {a2a_agents}")
    
    # Get tools from MCP config and A2A agents
    tools = await get_tools_from_config(
        mcp_config=mcp_config,
        selected_tools=selected_tools,
        a2a_agents=a2a_agents
    )
    
    # logger.info(f"[deepagents_node] Loaded {len(tools)} tools")
    
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
    
    # logger.info("[deepagents_node] Creating deep agent")
    
    # Create deep agent
    deep_agent = create_deep_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt
    )
    
    logger.info("[deepagents_node] Invoking deep agent")
    
    # Invoke deep agent with the current state
    result = await deep_agent.ainvoke(state, config)
    
    # logger.info("[deepagents_node] Deep agent execution complete")
    
    # Extract todos from deepagents state if available
    # Deepagents stores todos in the 'todos' field of its internal state
    # todos = result.get("todos", []) if isinstance(result, dict) else []
    
    # # Transform todos to match frontend TodoItem format
    # transformed_todos = []
    # if todos and isinstance(todos, list):
    #     for todo in todos:
    #         if isinstance(todo, dict):
    #             transformed_todos.append({
    #                 "id": todo.get("id"),
    #                 "description": todo.get("content", todo.get("description", str(todo))),
    #                 "status": todo.get("status", "pending"),
    #                 "created_at": todo.get("created_at"),
    #                 "completed_at": todo.get("completed_at")
    #             })
    #         else:
    #             # Handle simple string todos
    #             transformed_todos.append({
    #                 "description": str(todo),
    #                 "status": "pending"
    #             })
    
    # logger.info(f"[deepagents_node] Extracted todos: {(transformed_todos)}; result: {result}")
    
    return {
        **state,
        "messages": result.get("messages", state.get("messages", [])),
        "plan_mode": True  # Indicate that plan mode is active
    }


# from langgraph.checkpoint.memory import MemorySaver
# checkpointer = MemorySaver()
# deep_agent = create_deep_agent(
#     model=get_llm({"model": "gpt-4o-mini"}),
#     # tools=tools,
#     system_prompt="You are an expert researcher. Your job is to conduct \
# thorough research and provide accurate and detailed information. Note: Don't forget to mark a todo as completed if a step is completed.",
#     checkpointer=checkpointer
# )
