
import logging
from typing import Optional, List, Any
from langchain_core.tools import tool
from django.contrib.auth.models import User
from app.mcp.models import MCPServer
from asgiref.sync import sync_to_async

import os
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

def get_mcp_management_tools(user_id: Optional[int] = None) -> List[Any]:
    """
    Create tools for managing MCP servers with user context.
    
    Args:
        user_id: ID of the authenticated user. If None, tools will fail with auth error.
    """
    
    @tool
    async def add_mcp_server(
        name: str,
        url: str,
        transport: str,
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
            description: Description of the server
            requires_oauth2: Whether the server requires OAuth2
            is_public: Whether to make the server public (defaults to False)
        """
        if not user_id:
            return "Error: You must be authenticated to add an MCP server."
            
        try:
            # Check if name is taken by this user
            exists = await MCPServer.objects.filter(
                name=name, 
                owner_id=user_id
            ).aexists()
            
            if exists:
                return f"Error: You already have a server named '{name}'."
                
            # Create the server
            # Note: sync_to_async needed for some ORM operations if not using async capability fully,
            # but acreate is available for creation.
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
            
            return f"Successfully added MCP server '{name}' (ID: {server.id})."
            
        except Exception as e:
            logger.exception(f"Error adding MCP server: {e}")
            return f"Error adding MCP server: {str(e)}"

    @tool
    async def delete_mcp_server(name: str) -> str:
        """
        Delete an MCP server by name.
        
        Args:
            name: Name of the server to delete
        """
        if not user_id:
            return "Error: You must be authenticated to delete an MCP server."
            
        try:
            # Find server owned by user
            try:
                server = await MCPServer.objects.aget(name=name, owner_id=user_id)
            except MCPServer.DoesNotExist:
                return f"Error: Server '{name}' not found or you do not have permission to delete it."
                
            await server.adelete()
            return f"Successfully deleted MCP server '{name}'."
            
        except Exception as e:
            logger.exception(f"Error deleting MCP server: {e}")
            return f"Error deleting MCP server: {str(e)}"
            
    return [add_mcp_server, delete_mcp_server]
