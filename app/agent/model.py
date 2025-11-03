"""
This module provides a function to get a model based on the configuration.
"""
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from app.agent.types import AgentState


def get_llm(state: AgentState) -> BaseChatModel:
    """
    Returns the appropriate chat model based on the agent's state.
    Supports OpenAI, DeepSeek, and OpenRouter models.
    """
    model_name = state.get("model", "deepseek")
    print(f"Model: {model_name}")

    # Handle OpenRouter models first (detected by :free suffix)
    if ":free" in model_name:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment variables."
            )
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            # temperature=0,
            streaming=True,
            default_headers={
                "HTTP-Referer": os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000"),
                "X-Title": "MCP Assistant",
            }
        )

    # Handle DeepSeek models
    if model_name.startswith("deepseek"):
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment variables."
            )
        return ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            # temperature=0,
            streaming=True,
        )

    # Handle OpenAI models (default)
    print(f"else block: {model_name}")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment variables."
        )
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        # temperature=0,
        streaming=True,
    )