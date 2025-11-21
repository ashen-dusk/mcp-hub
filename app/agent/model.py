"""
This module provides a function to get a model based on the configuration.
"""
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from app.agent.types import AgentState


def get_llm(state: AgentState) -> BaseChatModel:
    """
    Returns the appropriate chat model based on the agent's state.
    Supports OpenAI, DeepSeek, and OpenRouter models.
    Extracts temperature and max_tokens from assistant config in state.
    """
    model_name = state.get("model", "deepseek")

    # Extract temperature and max_tokens from assistant config
    assistant = state.get("assistant", {})
    assistant_config = assistant.get("config", {}) if assistant else {}
    temperature = assistant_config.get("temperature", 0)  # default 0
    max_tokens = assistant_config.get("max_tokens")  # can be None

    print(f"Model: {model_name}, Temperature: {temperature}, Max Tokens: {max_tokens}")

    # Handle Claude/Anthropic models with extended thinking
    if model_name.startswith("claude"):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment variables."
            )

        # Build model kwargs with extended thinking enabled
        model_kwargs = {
            "model": model_name,
            "api_key": api_key,
            "temperature": temperature,
            "streaming": True,
        }
        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens

        # Enable extended thinking for supported models
        # This shows the model's reasoning process before generating the final answer
        if "sonnet" in model_name or "opus" in model_name:
            model_kwargs["extended_thinking"] = True
            print(f"✨ Extended thinking enabled for {model_name}")

        return ChatAnthropic(**model_kwargs)

    # Handle OpenRouter models first (detected by :free suffix)
    if ":free" in model_name:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment variables."
            )

        # Build model kwargs
        model_kwargs = {
            "model": model_name,
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
            "temperature": temperature,
            "streaming": True,
            "default_headers": {
                "HTTP-Referer": os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000"),
                "X-Title": "MCP Assistant",
            }
        }
        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens

        return ChatOpenAI(**model_kwargs)

    # Handle DeepSeek models
    if model_name.startswith("deepseek"):
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment variables."
            )

        # Build model kwargs
        model_kwargs = {
            "model": model_name,
            "api_key": api_key,
            "temperature": temperature,
            "streaming": True,
        }
        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens

        return ChatDeepSeek(**model_kwargs)

    # Handle OpenAI models (default)
    print(f"else block: {model_name}")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment variables."
        )

    # Build model kwargs
    model_kwargs = {
        "model": model_name,
        "api_key": api_key,
        "temperature": temperature,
        "streaming": True,
    }
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**model_kwargs)