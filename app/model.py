"""
This module provides a function to get a model based on the configuration.
"""
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from app.schema import AgentState


def get_llm(state: AgentState) -> BaseChatModel:
    """
    Returns the appropriate chat model based on the agent's state.
    """
    model_name = state.get("model", "deepseek")
    print(f"Model: {model_name}")
    
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
            temperature=0,
            streaming=True,
        )
    
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
        temperature=0,
        streaming=True,
    )