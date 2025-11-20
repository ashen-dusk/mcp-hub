"""
Shared utility functions for MCP module.

This module contains reusable utility functions to avoid code duplication
and improve maintainability.
"""

import json
import logging
import re
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


def extract_tool_result(result: Any) -> Dict[str, Any]:
    """
    Extract content from FastMCP CallToolResult and format as JSON.

    Handles CallToolResult objects by extracting text content,
    attempting to parse JSON strings, or returning the result as-is.
    Converts is_error to success for better API semantics.

    Args:
        result: The result from FastMCP client.call_tool()

    Returns:
        JSON-serializable dictionary with extracted content
    """
    def _try_parse_json(text: str) -> Any:
        """Try to parse JSON from a text string, handling embedded JSON."""
        if not isinstance(text, str):
            return text

        # Try direct JSON parse first
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find and parse JSON object/array embedded in text
        try:
            json_match = re.search(r'[\{\[].*[\}\]]', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            pass

        # Return original text if JSON parsing fails
        return text

    # If already JSON-compatible type, return as-is
    if isinstance(result, (dict, list)):
        return result
    if isinstance(result, (str, int, float, bool, type(None))):
        return {"content": result}

    # Check if it's a CallToolResult object (has content attribute)
    if hasattr(result, 'content') and hasattr(result, 'is_error'):
        extracted = {
            "success": not result.is_error,
        }

        # Extract structured content if available
        if hasattr(result, 'structured_content') and result.structured_content:
            extracted["structured_content"] = result.structured_content
            return extracted

        # Extract data if available
        if hasattr(result, 'data') and result.data:
            extracted["data"] = result.data
            return extracted

        # Extract content from content blocks
        if hasattr(result, 'content') and result.content:
            content_list = []
            for content_item in result.content:
                # Handle TextContent
                if hasattr(content_item, 'text'):
                    text = content_item.text
                    # Try to parse JSON from the text
                    parsed = _try_parse_json(text)
                    content_list.append(parsed)
                # Handle other content types
                elif hasattr(content_item, 'type') and hasattr(content_item, '__dict__'):
                    content_list.append({
                        "type": getattr(content_item, 'type', None),
                        "data": str(content_item)
                    })
                else:
                    content_list.append(str(content_item))

            # Return as single item if only one content item
            if len(content_list) == 1:
                extracted["content"] = content_list[0]
            else:
                extracted["content"] = content_list

            return extracted

    # Fallback: convert to string
    return {"content": str(result)}


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
