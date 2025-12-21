
import logging
from typing import Optional, List, Any
from langchain.tools import tool, ToolRuntime
from django.contrib.auth.models import User
from app.mcp.models import MCPServer
from asgiref.sync import sync_to_async

import os
import json
import platform
from datetime import datetime, timezone, timedelta
from langchain_tavily import TavilySearch
from app.a2a.client import send_a2a_message

logger = logging.getLogger(__name__)

@tool
def get_current_datetime() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is not set.")
    search = TavilySearch(max_results=3)
    return search.invoke(query)

@tool
def get_system_info() -> str:
    """Return basic information about the system environment."""
    return f"{platform.system()} {platform.release()} ({platform.processor()})"

@tool
async def send_message_to_a2a_agent(task: str, agentUrl: str, agentName: str) -> str:
    """
    Sends a task to an A2A agent. Please specify the agent URL and agent name.
    
    Args:
        task: The comprehensive conversation-context summary and goal to be achieved regarding the user inquiry.
        agentUrl: The URL of the A2A agent to communicate with (e.g., http://localhost:9001)
        agentName: The name of the A2A agent (e.g., "Analysis Agent")

    Returns:
        Response from the A2A agent
    """

    try:
        if not task:
            raise ValueError("Missing required parameter: task")
        
        if not agentUrl and not agentName:
            raise ValueError("Must provide either agentUrl or agentName")

        # Use the URL directly if provided, otherwise we'll need to look it up
        url_to_use = agentUrl
        
        if not url_to_use:
            # agentName was provided, return error asking for URL
            raise ValueError(f"Agent name '{agentName}' provided but URL is required. Please use agentUrl parameter with the agent's URL.")

        logger.info(f"Delegating to A2A agent at {url_to_use}")
        logger.info(f"Task: {task}")

        # Send message to A2A agent using official a2a library
        response = await send_a2a_message(agent_url=url_to_use, message=task)

        logger.info(f"Received response from A2A agent at {url_to_use}")
        return response

    except Exception as e:
        error_msg = f"Error communicating with A2A agent: {str(e)}"
        logger.error(error_msg)
        return error_msg

@tool
async def add_mcp_server(
    name: str,
    url: str,
    transport: str,
    runtime: ToolRuntime,
    description: str = "",
    requires_oauth2: bool = False,
    is_public: bool = False
) -> str:
    """
    Add a new MCP server to the registry.
    
    Args:
        name: Name of the server
        url: URL or command to connect to the server
        transport: Transport type (sse, websocket, stdio, streamable_http)
        runtime: ToolRuntime to access state
        description: Description of the server
        requires_oauth2: Whether the server requires OAuth2
        is_public: Whether to make the server public (defaults to False)
    """
    try:
        user_id = runtime.state.get("user_id")
        if not user_id:
            return json.dumps({"error": "Authentication required"})

        # Check if name is taken by this user
        exists = await MCPServer.objects.filter(
            name=name, 
            owner_id=user_id
        ).aexists()
        
        if exists:
            return json.dumps({"error": f"Server '{name}' already exists"})
            
        # Create the server
        server = await MCPServer.objects.acreate(
            name=name,
            url=url,
            transport=transport,
            description=description,
            requires_oauth2=requires_oauth2,
            is_public=is_public,
            owner_id=user_id,
            enabled=True
        )
        
        return json.dumps({
            "success": True,
            "message": f"Successfully added MCP server '{name}'",
            "server_id": server.id,
            "name": name
        })
        
    except Exception as e:
        logger.exception(f"Error adding MCP server: {e}")
        return json.dumps({"error": str(e)})

@tool
async def delete_mcp_server(name: str, runtime: ToolRuntime) -> str:
    """
    Delete an MCP server by name.
    
    Args:
        name: Name of the server to delete
        runtime: ToolRuntime to access state
    """
    try:
        user_id = runtime.state.get("user_id")
        if not user_id:
            return json.dumps({"error": "Authentication required"})

        # Find server owned by user
        try:
            server = await MCPServer.objects.aget(name=name, owner_id=user_id)
        except MCPServer.DoesNotExist:
            return json.dumps({"error": f"Server '{name}' not found or permission denied"})
            
        await server.adelete()
        return json.dumps({
            "success": True,
            "message": f"Successfully deleted MCP server '{name}'",
            "name": name
        })
        
    except Exception as e:
        logger.exception(f"Error deleting MCP server: {e}")
        return json.dumps({"error": str(e)})

@tool
async def list_mcp_servers(runtime: ToolRuntime, page: int = 1, page_size: int = 10) -> str:
    """
    List all MCP servers owned by the authenticated user with pagination.
    
    Args:
        runtime: ToolRuntime to access state
        page: Page number (default 1)
        page_size: Number of items per page (default 10)
        
    Returns:
        JSON string containing list of servers and pagination metadata.
    """
    try:
        user_id = runtime.state.get("user_id")
        if not user_id:
            return json.dumps({"error": "Authentication required"})

        # Ensure valid pagination params
        page = max(1, page)
        page_size = max(1, min(100, page_size))  # Cap at 100

        # Base queryset ordered by creation time
        qs = MCPServer.objects.filter(owner_id=user_id).order_by('-created_at')
        
        # Get total count asynchronously
        total_count = await qs.acount()
        
        # Calculate pagination
        start = (page - 1) * page_size
        end = start + page_size
        total_pages = (total_count + page_size - 1) // page_size
        
        # Get page data
        servers = []
        async for server in qs[start:end]:
            servers.append({
                "name": server.name,
                "transport": server.transport,
                "url": server.url,
                "is_public": server.is_public,
                "description": server.description,
                "created_at": server.created_at.isoformat() if server.created_at else None
            })
        
        return json.dumps({
            "servers": servers,
            "pagination": {
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
        })
        
    except Exception as e:
        logger.exception(f"Error listing MCP servers: {e}")
        return json.dumps({"error": str(e)})
