"""
This module provides a function to get a model based on the configuration.
"""
import os
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from app.agent.types import AgentState

logger = logging.getLogger(__name__)


def get_llm(state: AgentState) -> BaseChatModel:
    """
    Returns the appropriate chat model based on the agent's state.
    Supports OpenAI, DeepSeek, Anthropic, and OpenRouter models.
    """
    model_name = state.get("model", "gpt-4o-mini")

    # Extract temperature and max_tokens from assistant config
    assistant = state.get("assistant", {})
    assistant_config = assistant.get("config", {}) if assistant else {}
    temperature = assistant_config.get("temperature", 0)  # default 0
    max_tokens = assistant_config.get("max_tokens")  # can be None

    # Get LLM provider and API key from assistant_config
    llm_provider = assistant_config.get("llm_provider")
    llm_api_key = assistant_config.get("llm_api_key")
    llm_name = assistant_config.get("llm_name")
    effective_model = llm_name or model_name

    logger.info(f"[get_llm] Model: {effective_model}, Provider: {llm_provider}, Temperature: {temperature}, Max Tokens: {max_tokens}")

    # 1. Handle OpenRouter models
    if ":free" in effective_model:
        api_key = llm_api_key if llm_api_key else os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OpenRouter API key not provided.")

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

    # 2. Handle Anthropic models
    if effective_model.startswith("claude") or llm_provider == "anthropic":
        logger.info(f"[get_llm] Using Anthropic model: {effective_model}")
        api_key = llm_api_key if llm_api_key else os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key not provided. "
                "Please configure it in LLM settings or set ANTHROPIC_API_KEY environment variable."
            )

        model_kwargs = {
            "model": effective_model,
            "api_key": api_key,
            "temperature": temperature,
            "streaming": True,
            # "thinking": {"type": "enabled", "budget_tokens": 1024}
        }
        # Anthropic requires max_tokens to be passed; 
        # if your state doesn't have it, we provide a sensible default (e.g., 4096)
        model_kwargs["max_tokens"] = max_tokens if max_tokens is not None else 4096

        return ChatAnthropic(**model_kwargs)

    # 3. Handle DeepSeek models
    if effective_model.startswith("deepseek") or llm_provider == "deepseek":
        logger.info(f"[get_llm] Using DeepSeek model: {effective_model}")
        api_key = llm_api_key if llm_api_key else os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DeepSeek API key not provided.")

        model_kwargs = {
            "model": effective_model,
            "api_key": api_key,
            "temperature": temperature,
            "streaming": True,
        }
        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens
        return ChatDeepSeek(**model_kwargs)

    # 4. Handle OpenAI models (default)
    logger.info(f"[get_llm] Using OpenAI model: {effective_model}")
    api_key = llm_api_key if llm_api_key else os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI API key not provided.")

    model_kwargs = {
        "model": effective_model,
        "api_key": api_key,
        "streaming": True,
        "use_responses_api": True,
        "output_version": "responses/v1",
        "reasoning_effort": "low",
    }
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**model_kwargs)