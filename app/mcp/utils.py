"""
Shared utility functions for MCP module.

This module contains reusable utility functions to avoid code duplication
and improve maintainability.
"""

import json
import logging
from typing import Any, Dict, List
from pydantic.v1 import BaseModel


class EmptyArgsSchema(BaseModel):
    """Schema for tools with no parameters (OpenAI requirement)."""
    pass


def safe_json_dumps(obj: Any, default_value: str = "{}") -> str:
    """
    Safely serialize an object to JSON, handling non-serializable types.

    Args:
        obj: Object to serialize
        default_value: Value to return if serialization fails

    Returns:
        JSON string representation of the object
    """
    def json_serializer(item):
        if callable(item):
            return str(item)
        elif hasattr(item, '__dict__'):
            return item.__dict__
        else:
            return str(item)

    try:
        return json.dumps(obj, default=json_serializer)
    except Exception as e:
        logging.warning(f"Failed to serialize object to JSON: {e}")
        return default_value


def patch_tool_schema(tool: Any) -> Any:
    """
    Ensure a single tool has a valid schema for OpenAI.

    OpenAI requires a non-empty object for function parameters.
    A schema is invalid if it's missing or if it's a dict without 'properties'.

    Args:
        tool: Tool object to patch

    Returns:
        Patched tool object
    """
    args_schema = getattr(tool, "args_schema", None)
    is_invalid_dict_schema = (
        isinstance(args_schema, dict) and "properties" not in args_schema
    )

    if not args_schema or is_invalid_dict_schema:
        tool.args_schema = EmptyArgsSchema

    return tool


def patch_tools_schema(tools: List[Any]) -> List[Any]:
    """
    Patch multiple tools to ensure valid schemas.

    Args:
        tools: List of tool objects

    Returns:
        List of patched tools
    """
    return [patch_tool_schema(tool) for tool in tools]


def serialize_tool(tool: Any) -> Dict[str, Any]:
    """
    Convert a single tool object to a serializable dict for GraphQL.

    Handles both FastMCP tools (inputSchema/input_schema) and
    LangChain MCP tools (args_schema).

    Args:
        tool: Tool object to serialize

    Returns:
        Dictionary with tool information
    """
    schema_dict = {}

    # Handle FastMCP tools
    if hasattr(tool, "inputSchema") and tool.inputSchema:
        schema_dict = tool.inputSchema
    elif hasattr(tool, "input_schema") and tool.input_schema:
        schema_dict = tool.input_schema
    # Handle LangChain MCP tools
    elif hasattr(tool, "args_schema"):
        args_schema = tool.args_schema
        if hasattr(args_schema, "schema") and callable(args_schema.schema):
            try:
                schema_dict = args_schema.schema()
            except Exception:
                pass
        elif isinstance(args_schema, dict):
            schema_dict = args_schema

    return {
        "name": getattr(tool, 'name', str(tool)),
        "description": getattr(tool, 'description', '') or '',
        "schema": safe_json_dumps(schema_dict) if schema_dict else "{}",
    }


def serialize_tools(tools: List[Any]) -> List[Dict[str, Any]]:
    """
    Convert tool objects to a serializable list of dicts.

    Args:
        tools: List of tool objects

    Returns:
        List of dictionaries with tool information
    """
    return [serialize_tool(tool) for tool in tools]


def generate_anonymous_session_key(request) -> str:
    """
    Generate a unique session key for anonymous users.

    Creates a session identifier based on request characteristics
    without requiring Django session creation in async context.

    Args:
        request: Django request object

    Returns:
        Unique session key string
    """
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:50]
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')

    # Create a unique identifier for this anonymous session
    session_identifier = f"{ip}_{user_agent}_{forwarded_for}"
    return f"anon_{hash(session_identifier)}"
