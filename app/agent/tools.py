
import logging
from typing import Optional, List, Any
from langchain.tools import tool, ToolRuntime
from django.contrib.auth import get_user_model
from app.mcp.models import MCPServer
from asgiref.sync import sync_to_async

import os
import json
import platform
from datetime import datetime, timezone, timedelta
from langchain_tavily import TavilySearch
from app.a2a.client import send_a2a_message
import httpx

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
    Add a new MCP server or update an existing one.
    
    Args:
        name: Name of the server (unique identifier for updates)
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
        try:
            server = await MCPServer.objects.aget(name=name, owner_id=user_id)
            # Update existing server
            server.url = url
            server.transport = transport
            server.description = description
            server.requires_oauth2 = requires_oauth2
            server.is_public = is_public
            await server.asave()
            
            return json.dumps({
                "success": True,
                "message": f"Successfully updated MCP server '{name}'",
                "server_id": server.id,
                "name": name,
                "action": "updated"
            })
            
        except MCPServer.DoesNotExist:
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
                "name": name,
                "action": "created"
            })
        
    except Exception as e:
        logger.exception(f"Error adding/updating MCP server: {e}")
        return json.dumps({"error": str(e)})

@tool
async def delete_mcp_server(runtime: ToolRuntime, server_id: str = "", name: str = "") -> str:
    """
    Delete an MCP server by ID (preferred) or by name.
    
    Args:
        runtime: ToolRuntime to access state
        server_id: ID of the server to delete (preferred)
        name: Name of the server to delete (fallback)
    """
    try:
        user_id = runtime.state.get("user_id")
        if not user_id:
            return json.dumps({"error": "Authentication required"})
        if not server_id and not name:
            return json.dumps({"error": "Either server_id or name is required"})

        # Find server owned by user (ID preferred).
        try:
            if server_id:
                server = await MCPServer.objects.aget(pk=server_id, owner_id=user_id)
            else:
                server = await MCPServer.objects.aget(name=name, owner_id=user_id)
        except MCPServer.DoesNotExist:
            lookup_value = server_id or name
            lookup_field = "id" if server_id else "name"
            return json.dumps({"error": f"Server with {lookup_field} '{lookup_value}' not found or permission denied"})
            
        deleted_server_id = str(server.id)
        deleted_server_name = server.name
        await server.adelete()
        return json.dumps({
            "success": True,
            "message": f"Successfully deleted MCP server '{deleted_server_name}'",
            "id": deleted_server_id,
            "name": deleted_server_name
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
                "id": server.id,
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

@tool
async def search_servers(
    query: str,
    page: int = 1,
    page_size: int = 10
) -> str:
    """
    Search for public MCP servers by name.

    Args:
        query: Search query to filter servers by name (required).
        page: Page number (default: 1)
        page_size: Number of results per page (default: 10, max: 100)

    Returns:
        JSON string containing search results with server details and pagination info.
    """
    try:
        # Validate pagination parameters
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        # Calculate pagination
        start = (page - 1) * page_size
        end = start + page_size

        # Query public servers that match the search query
        qs = MCPServer.objects.filter(
            is_public=True,
            name__icontains=query
        ).select_related('owner').order_by('-created_at')

        # Get total count
        total_count = await qs.acount()
        total_pages = (total_count + page_size - 1) // page_size

        # Get page data
        servers = []
        async for server in qs[start:end]:
            servers.append({
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "transport": server.transport,
                "url": server.url,
                # "requiresOauth2": server.requires_oauth2,
                # "isPublic": server.is_public,
                # "isFeatured": server.is_featured,
                "createdAt": server.created_at.isoformat() if server.created_at else None,
                # "owner": server.owner.username if server.owner else None
            })

        result = {
            "success": True,
            "servers": servers,
            "pagination": {
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
        }

        logger.info(f"Successfully retrieved {len(servers)} servers matching '{query}'")
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.exception(f"Error searching servers: {e}")
        return json.dumps({"error": str(e)})

@tool
async def check_connections(runtime: ToolRuntime) -> str:
    """
    Check all active MCP connections for the authenticated user.

    Args:
        runtime: ToolRuntime to access state

    Returns:
        JSON string containing list of active connections with their status and metadata.
    """
    try:
        user_id = runtime.state.get("user_id")
        if not user_id:
            return json.dumps({"error": "Authentication required"})

        # Get the mcp-client base URL from environment
        mcp_client_url = os.environ.get("MCP_CLIENT_URL", "http://localhost:3000")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{mcp_client_url}/api/mcp/connections",
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved {data.get('count', 0)} connections")
                return json.dumps(data, indent=2)
            elif response.status_code == 401:
                return json.dumps({"error": "Unauthorized - Authentication failed"})
            else:
                return json.dumps({
                    "error": f"API request failed with status {response.status_code}",
                    "details": response.text
                })

    except httpx.TimeoutException:
        logger.error("Timeout while connecting to MCP client API")
        return json.dumps({"error": "Request timeout - MCP client API did not respond in time"})
    except Exception as e:
        logger.exception(f"Error checking connections: {e}")
        return json.dumps({"error": str(e)})

@tool
async def initiate_connection(
    server_url: str,
    runtime: ToolRuntime,
    server_id: str = "",
    server_name: str = "",
    transport_type: str = "streamable_http",
) -> str:
    """
    Initiate a connection to an MCP server with OAuth authentication.

    This tool triggers user authentication flow. The actual connection result
    will be provided through the interrupt/approval flow.

    Args:
        server_url: URL of the MCP server to connect to
        server_id: ID of the server
        server_name: Optional name for the server
        transport_type: Transport type (sse or streamable_http, default: streamable_http)

    Returns:
        JSON data about the MCP server indicating that the connection has established if successful.
    """
    # Safely get approval_response from runtime state
    approval_response = None
    if runtime.state and isinstance(runtime.state, dict):
        logger.info(f"[initiate_connection] runtime.state: {runtime.state}")
        approval_response = runtime.state.get("approval_response", {})

    # If approval_response is still None or not a dict, use empty dict
    if not approval_response or not isinstance(approval_response, dict):
        approval_response = {}

    status = "connected" if approval_response.get("connected", False) else "failed"
    success = approval_response.get("connected", False)
    message = "Connection established successfully." if success else "Connection failed or was not approved."
    logger.info(f"[initiate_connection] connection state: {approval_response}")
    # Prepare state for approval interrupt
    return json.dumps({
               "success": success,
               "message": message,
               "sessionId": approval_response.get("sessionId"),
               "serverUrl": approval_response.get("serverUrl"),
               "serverName": approval_response.get("serverName"),
               "serverId": approval_response.get("serverId"),
               "connected": approval_response.get("connected", False),
               "status": status
    });
