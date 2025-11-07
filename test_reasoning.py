#!/usr/bin/env python3
"""
Test script to verify reasoning functionality in the agent.
Run this to test both Claude extended thinking and custom reasoning.
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()


async def test_claude_extended_thinking():
    """Test Claude's native extended thinking feature."""
    print("\n" + "=" * 60)
    print("🧪 Testing Claude Extended Thinking")
    print("=" * 60 + "\n")

    # Check if API key is available
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY not found in environment")
        print("   Set it in .env to test Claude extended thinking")
        return

    from app.agent.types import AgentState
    from app.agent.chat import chat_node
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableConfig

    # Create test state
    state: AgentState = {
        "messages": [
            HumanMessage(content="Explain how to implement a binary search tree in Python. Be thorough.")
        ],
        "model": "claude-sonnet-4-5",
        "assistant": {
            "config": {
                "temperature": 0.7,
                "max_tokens": 2000
            }
        },
        "sessionId": "test-session-123"
    }

    config = RunnableConfig(
        configurable={"thread_id": "test-thread-123"}
    )

    print("📝 Question: Explain how to implement a binary search tree")
    print("🤖 Model: claude-sonnet-4-5")
    print("\n⏳ Generating response...\n")

    try:
        result = await chat_node(state, config)

        # Check for thinking blocks
        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]

            # Check additional_kwargs for thinking blocks
            thinking_blocks = last_message.additional_kwargs.get("thinking_blocks", [])

            if thinking_blocks:
                print("✅ Extended thinking captured!")
                print("\n💭 Thinking Process:")
                print("-" * 60)
                for i, thinking in enumerate(thinking_blocks, 1):
                    print(f"\n[Thinking Block {i}]")
                    print(thinking[:500] + "..." if len(thinking) > 500 else thinking)
                print("\n" + "-" * 60)
            else:
                print("⚠️  No thinking blocks found")
                print("   This might be because:")
                print("   - Extended thinking is not enabled for this model")
                print("   - The model didn't generate thinking for this prompt")

            # Print the actual response
            print("\n📤 Response:")
            print("-" * 60)
            response_content = last_message.content
            if isinstance(response_content, list):
                for block in response_content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        print(block.get("text", "")[:500] + "...")
                        break
            else:
                print(str(response_content)[:500] + "...")
            print("-" * 60)

        print("\n✅ Claude extended thinking test completed!\n")

    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()


async def test_custom_reasoning():
    """Test custom reasoning node for non-Claude models."""
    print("\n" + "=" * 60)
    print("🧪 Testing Custom Reasoning Node")
    print("=" * 60 + "\n")

    from app.agent.types import AgentState
    from app.agent.reasoning import reasoning_node, reasoning_chat_node
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableConfig

    # Test with OpenAI or DeepSeek
    model_to_test = "gpt-4o" if os.getenv("OPENAI_API_KEY") else "deepseek-chat"

    # Create test state
    state: AgentState = {
        "messages": [
            HumanMessage(content="How would you design a caching system for a web application?")
        ],
        "model": model_to_test,
        "assistant": {
            "config": {
                "temperature": 0.7,
                "max_tokens": 1500,
                "enable_reasoning": True
            }
        },
        "sessionId": "test-session-456"
    }

    config = RunnableConfig(
        configurable={"thread_id": "test-thread-456"}
    )

    print(f"📝 Question: How would you design a caching system?")
    print(f"🤖 Model: {model_to_test}")
    print("\n⏳ Generating reasoning...\n")

    try:
        # First, test reasoning node
        print("Step 1: Generate reasoning")
        reasoning_result = await reasoning_node(state, config)

        reasoning_content = reasoning_result.get("reasoning", "")
        if reasoning_content:
            print("✅ Reasoning generated!")
            print("\n🧠 Reasoning Process:")
            print("-" * 60)
            print(reasoning_content[:600] + "..." if len(reasoning_content) > 600 else reasoning_content)
            print("-" * 60)
        else:
            print("⚠️  No reasoning content generated")

        # Now test the full reasoning chat node
        print("\n⏳ Step 2: Generate final response...\n")
        final_result = await reasoning_chat_node(state, config)

        messages = final_result.get("messages", [])
        if messages:
            last_message = messages[-1]
            print("✅ Final response generated!")
            print("\n📤 Response:")
            print("-" * 60)
            response_content = str(last_message.content)
            print(response_content[:600] + "..." if len(response_content) > 600 else response_content)
            print("-" * 60)

        print("\n✅ Custom reasoning test completed!\n")

    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()


async def test_plan_execute_reasoning():
    """Test reasoning in plan-and-execute graph."""
    print("\n" + "=" * 60)
    print("🧪 Testing Plan-and-Execute with Reasoning")
    print("=" * 60 + "\n")

    try:
        from app.agent.plan_and_execute_with_reasoning import reasoning_plan_node
        from app.agent.types import AgentState
        from langchain_core.messages import HumanMessage
        from langchain_core.runnables import RunnableConfig

        model_to_test = "gpt-4o" if os.getenv("OPENAI_API_KEY") else "deepseek-chat"

        state: AgentState = {
            "messages": [
                HumanMessage(content="Create a simple REST API for a todo app with user authentication")
            ],
            "model": model_to_test,
            "assistant": {
                "config": {
                    "temperature": 0.7
                }
            },
            "sessionId": "test-session-789"
        }

        config = RunnableConfig(
            configurable={"thread_id": "test-thread-789"}
        )

        print(f"📝 Task: Create a REST API for todo app")
        print(f"🤖 Model: {model_to_test}")
        print("\n⏳ Generating planning reasoning...\n")

        result = await reasoning_plan_node(state, config)

        planning_reasoning = result.get("planning_reasoning", [])
        if planning_reasoning:
            print("✅ Planning reasoning captured!")
            print("\n📋 Planning Thoughts:")
            print("-" * 60)
            for item in planning_reasoning:
                print(item.get("content", "")[:500] + "...")
            print("-" * 60)
        else:
            print("⚠️  No planning reasoning captured")

        print("\n✅ Plan-and-execute reasoning test completed!\n")

    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("🚀 Reasoning Functionality Test Suite")
    print("=" * 60)

    # Check which API keys are available
    available_providers = []
    if os.getenv("ANTHROPIC_API_KEY"):
        available_providers.append("Anthropic (Claude)")
    if os.getenv("OPENAI_API_KEY"):
        available_providers.append("OpenAI")
    if os.getenv("DEEPSEEK_API_KEY"):
        available_providers.append("DeepSeek")

    print(f"\n📦 Available providers: {', '.join(available_providers) if available_providers else 'None'}")

    if not available_providers:
        print("\n⚠️  No API keys found!")
        print("   Please set at least one of:")
        print("   - ANTHROPIC_API_KEY")
        print("   - OPENAI_API_KEY")
        print("   - DEEPSEEK_API_KEY")
        return

    # Run tests based on available providers
    if os.getenv("ANTHROPIC_API_KEY"):
        await test_claude_extended_thinking()

    if os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY"):
        await test_custom_reasoning()
        await test_plan_execute_reasoning()

    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
