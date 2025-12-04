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
    Extracts temperature and max_tokens from assistant config in state.
    Uses API key from state if provided, otherwise falls back to environment variables.
    """
    model_name = state.get("model", "gpt-4o-mini")

    # Extract temperature and max_tokens from assistant config
    assistant = state.get("assistant", {})
    assistant_config = assistant.get("config", {}) if assistant else {}
    temperature = assistant_config.get("temperature", 0)  # default 0
    max_tokens = assistant_config.get("max_tokens")  # can be None

    # Get LLM provider and API key from assistant_config (supports both DB and localStorage)
    llm_provider = assistant_config.get("llm_provider")
    llm_api_key = assistant_config.get("llm_api_key")
    llm_name = assistant_config.get("llm_name")
    effective_model = llm_name or model_name

    print(f"Model: {effective_model}, Provider: {llm_provider}, Temperature: {temperature}, Max Tokens: {max_tokens}")

    # Handle OpenRouter models first (detected by :free suffix)
    if ":free" in effective_model:
        # Use user-provided API key or fallback to environment variable
        api_key = llm_api_key if llm_api_key else os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenRouter API key not provided. "
                "Please configure it in LLM settings or set OPENROUTER_API_KEY environment variable."
            )

        # Build model kwargs
        model_kwargs = {
            "model": effective_model,
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
    if model_name.startswith("deepseek") or llm_provider == "deepseek":
        # Use user-provided API key or fallback to environment variable
        api_key = llm_api_key if llm_api_key else os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "DeepSeek API key not provided. "
                "Please configure it in LLM settings or set DEEPSEEK_API_KEY environment variable."
            )

        # Build model kwargs
        model_kwargs = {
            "model": effective_model,
            "api_key": api_key,
            "temperature": temperature,
            "streaming": True,
        }
        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens

        return ChatDeepSeek(**model_kwargs)

    # Handle OpenAI models (default)
    print(f"else block: {model_name}")
    # Use user-provided API key or fallback to environment variable
    api_key = llm_api_key if llm_api_key else os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OpenAI API key not provided. "
            "Please configure it in LLM settings or set OPENAI_API_KEY environment variable."
        )

    # Build model kwargs
    model_kwargs = {
        "model": effective_model,
        "reasoning_effort": "medium",
        "api_key": api_key,
        "temperature": temperature,
        "streaming": True,
    }
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**model_kwargs)