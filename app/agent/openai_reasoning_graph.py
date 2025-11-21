"""
Ready-to-use LangGraph with reasoning for OpenAI models.
This graph adds visible reasoning/thinking to your OpenAI-powered agent.

Usage:
    from app.agent.openai_reasoning_graph import openai_reasoning_graph

    agent = LangGraphAGUIAgent(
        name="mcpAssistant",
        description="OpenAI Assistant with reasoning",
        graph=openai_reasoning_graph
    )
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.types import AgentState
from app.agent.reasoning import reasoning_chat_node
from app.agent.agent import async_tool_node, should_continue


def create_openai_reasoning_graph():
    """
    Create a graph that adds reasoning capabilities to OpenAI models.

    Flow:
    START → chat (with reasoning) → [tools or END]
                                ↓
                             tools → back to chat

    The chat node automatically:
    1. Generates reasoning about the user's question
    2. Uses that reasoning to create a better response
    3. Returns both reasoning and response for frontend display
    """
    graph_builder = StateGraph(AgentState)

    # Add nodes
    # reasoning_chat_node combines reasoning + chat in one node
    graph_builder.add_node("chat", reasoning_chat_node)
    graph_builder.add_node("tools", async_tool_node)

    # Add edges
    graph_builder.add_edge(START, "chat")

    # Conditional routing after chat
    graph_builder.add_conditional_edges(
        "chat",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )

    # After tools, go back to chat
    graph_builder.add_edge("tools", "chat")

    # Compile with checkpointer for conversation memory
    checkpointer = MemorySaver()
    return graph_builder.compile(checkpointer=checkpointer)


# Export the compiled graph
openai_reasoning_graph = create_openai_reasoning_graph()


# Alternative: Graph with explicit reasoning node (more control)
def create_openai_reasoning_graph_explicit():
    """
    Create a graph with explicit reasoning node for more control.

    Flow:
    START → reasoning → chat → [tools or END]
                               ↓
                            tools → back to chat

    This gives you more visibility and control over the reasoning step.
    """
    from app.agent.reasoning import reasoning_node

    graph_builder = StateGraph(AgentState)

    # Add nodes
    graph_builder.add_node("reasoning", reasoning_node)  # Explicit reasoning
    graph_builder.add_node("chat", reasoning_chat_node)  # Chat with reasoning context
    graph_builder.add_node("tools", async_tool_node)

    # Add edges
    graph_builder.add_edge(START, "reasoning")  # Start with reasoning
    graph_builder.add_edge("reasoning", "chat")  # Then chat

    # Conditional routing after chat
    graph_builder.add_conditional_edges(
        "chat",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )

    # After tools, skip reasoning and go directly to chat
    # (reasoning only needed for initial user question)
    graph_builder.add_edge("tools", "chat")

    # Compile
    checkpointer = MemorySaver()
    return graph_builder.compile(checkpointer=checkpointer)


# Export alternative graph
openai_reasoning_graph_explicit = create_openai_reasoning_graph_explicit()


# Conditional reasoning graph (toggle on/off)
def create_openai_conditional_reasoning_graph():
    """
    Create a graph where reasoning can be toggled on/off via config.

    Flow with reasoning enabled:
    START → reasoning → chat → [tools or END]

    Flow with reasoning disabled:
    START → chat → [tools or END]

    Toggle via assistant config:
    {
        "assistant": {
            "config": {
                "enable_reasoning": true  # or false
            }
        }
    }
    """
    from app.agent.reasoning import reasoning_node
    from app.agent.chat import chat_node

    def should_use_reasoning(state: AgentState) -> str:
        """Decide whether to use reasoning based on config."""
        assistant_config = state.get("assistant", {}).get("config", {})
        use_reasoning = assistant_config.get("enable_reasoning", False)

        if use_reasoning:
            return "reasoning"
        else:
            return "chat"

    graph_builder = StateGraph(AgentState)

    # Add nodes
    graph_builder.add_node("reasoning", reasoning_node)
    graph_builder.add_node("chat", reasoning_chat_node)
    graph_builder.add_node("chat_no_reasoning", chat_node)  # Regular chat without reasoning
    graph_builder.add_node("tools", async_tool_node)

    # Conditional start - use reasoning or not
    graph_builder.add_conditional_edges(
        START,
        should_use_reasoning,
        {
            "reasoning": "reasoning",
            "chat": "chat_no_reasoning"
        }
    )

    # After reasoning, go to chat
    graph_builder.add_edge("reasoning", "chat")

    # Conditional routing after both chat nodes
    graph_builder.add_conditional_edges(
        "chat",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )

    graph_builder.add_conditional_edges(
        "chat_no_reasoning",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )

    # After tools, go back to appropriate chat node
    def route_after_tools(state: AgentState) -> str:
        assistant_config = state.get("assistant", {}).get("config", {})
        if assistant_config.get("enable_reasoning", False):
            return "chat"
        return "chat_no_reasoning"

    graph_builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "chat": "chat",
            "chat_no_reasoning": "chat_no_reasoning"
        }
    )

    # Compile
    checkpointer = MemorySaver()
    return graph_builder.compile(checkpointer=checkpointer)


# Export conditional graph
openai_conditional_reasoning_graph = create_openai_conditional_reasoning_graph()


# Export all variants
__all__ = [
    "openai_reasoning_graph",  # Default - always use reasoning
    "openai_reasoning_graph_explicit",  # Explicit reasoning node
    "openai_conditional_reasoning_graph",  # Toggle reasoning on/off
]
