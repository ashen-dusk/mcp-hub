"""
Reasoning module for adding chain-of-thought reasoning to any LLM.
This provides reasoning capabilities for models that don't have native extended thinking.
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from app.agent.types import AgentState
from app.agent.model import get_llm


async def reasoning_node(state: AgentState, config: RunnableConfig):
    """
    Generate explicit reasoning before the main response.
    This node asks the LLM to think through the problem step-by-step.
    Works with any LLM (OpenAI, DeepSeek, OpenRouter, etc.)
    """
    messages = state.get("messages", [])

    # Get the last user message
    last_user_message = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_message = msg
            break

    if not last_user_message:
        # No user message to reason about, skip reasoning
        return state

    # Create a reasoning prompt
    reasoning_prompt = f"""Before answering the user's question, let's think through this step-by-step:

User's question: {last_user_message.content}

Please provide your reasoning and thought process. Break down the problem, consider different approaches, and explain your thinking. After your reasoning, I'll provide the final answer in the next step.

Think step-by-step:"""

    llm = get_llm(state)

    # Generate reasoning
    reasoning_response = await llm.ainvoke([
        SystemMessage(content="You are a helpful assistant that thinks step-by-step before answering."),
        HumanMessage(content=reasoning_prompt)
    ])

    # Store reasoning in state with special marker
    reasoning_message = AIMessage(
        content=reasoning_response.content,
        additional_kwargs={
            "type": "reasoning",
            "is_reasoning": True
        }
    )

    print(f"🧠 Generated reasoning: {reasoning_response.content[:100]}...")

    # Add reasoning to messages but mark it so it can be displayed differently
    return {
        **state,
        "reasoning": reasoning_response.content,  # Store for reference
        # Don't add to messages yet - let the frontend handle display
    }


async def reasoning_chat_node(state: AgentState, config: RunnableConfig):
    """
    Enhanced chat node that incorporates reasoning into the response.
    Use this instead of regular chat_node when you want visible reasoning.
    """
    from app.agent.chat import chat_node, get_tools

    # First, generate reasoning if not already present
    if not state.get("reasoning"):
        state = await reasoning_node(state, config)

    # Now proceed with normal chat, but include reasoning context
    messages = state.get("messages", [])
    reasoning = state.get("reasoning", "")

    # Add reasoning as context for the actual response
    if reasoning:
        # Create a system message that includes the reasoning
        reasoning_context = f"""
You have already thought through this problem step-by-step:

{reasoning}

Now provide a clear, concise answer to the user based on your reasoning above.
You can reference your reasoning but focus on giving a direct, helpful response.
"""

        # Temporarily add reasoning context
        enhanced_messages = [
            SystemMessage(content=reasoning_context),
            *messages
        ]

        # Update state with enhanced messages temporarily
        temp_state = {**state, "messages": enhanced_messages}

        # Call the normal chat node
        result = await chat_node(temp_state, config)

        # Restore original messages but keep the new response
        result["messages"] = messages + [result["messages"][-1]]

        # Clear reasoning for next turn
        result["reasoning"] = None

        return result
    else:
        # No reasoning, just use normal chat
        return await chat_node(state, config)
