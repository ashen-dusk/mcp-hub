# MCP Server Connection Management

This document describes the new connect/disconnect functionality for MCP servers in the Django AGUI application.

## Overview

The MCP (Model Context Protocol) manager now supports:
- **Connecting** to individual MCP servers with health checks
- **Disconnecting** from servers and removing them from the adapter map
- **Retrieving tool information** from connected servers
- **Tracking connection status** and server information

## Key Features

### 1. Server Connection
- Performs health checks before connecting
- Returns detailed tool information upon successful connection
- Handles connection timeouts and errors gracefully
- Stores connection metadata (timestamp, configuration, tools)

### 2. Server Disconnection
- Safely closes client connections
- Removes servers from the internal adapter map
- Cleans up connection tracking data

### 3. Tool Information
- Extracts tool names, descriptions, and schemas
- Provides serializable tool information for GraphQL API
- Supports querying tools from specific connected servers

## GraphQL Schema

### Types

```graphql
type MCPServerType {
  name: String!
  transport: String!
  url: String
  command: String
  argsJson: String
  enabled: Boolean!
  connectionStatus: String!
  connectedAt: Float
  toolCount: Int!
  tools: [ToolInfo!]!
}

type ToolInfo {
  name: String!
  description: String!
  schema: String!  # JSON string representation of the schema
}

type ConnectionResult {
  success: Boolean!
  message: String!
  tools: [ToolInfo!]!
  serverName: String!
  connectionStatus: String!
}

type DisconnectResult {
  success: Boolean!
  message: String!
}



type ServerHealthInfo {
  status: String!
  tools: [ToolInfo!]!
}
```

## API Endpoints

### GraphQL Queries

#### `mcpServers`
Get all configured MCP servers:
```graphql
query {
  mcpServers {
    name
    transport
    url
    command
    argsJson
    enabled
  }
}
```

**Response:**
```json
{
  "data": {
    "mcpServers": [
      {
        "name": "my-server",
        "transport": "stdio",
        "url": null,
        "command": "python",
        "argsJson": "[\"server.py\"]",
        "enabled": true,
        "connectionStatus": "CONNECTED",
        "connectedAt": 1703123456.789,
        "toolCount": 3,
        "tools": [
          {
            "name": "get_weather",
            "description": "Get current weather information",
            "schema": "{\"type\":\"object\",\"properties\":{\"location\":{\"type\":\"string\"}}}"
          }
        ]
      }
    ]
  }
}
```



#### `mcpServerHealth(name: String!)`
Check server health and get available tools:
```graphql
query GetServerHealth($serverName: String!) {
  mcpServerHealth(name: $serverName) {
    status
    tools {
      name
      description
      schema
    }
  }
}
```

**Variables:**
```json
{
  "serverName": "my-server"
}
```

**Response:**
```json
{
  "data": {
    "mcpServerHealth": {
      "status": "OK",
      "tools": [
        {
          "name": "get_weather",
          "description": "Get current weather information",
          "schema": "{\"type\":\"object\",\"properties\":{\"location\":{\"type\":\"string\"}}}"
        }
      ]
    }
  }
}
```

### GraphQL Mutations

#### `saveMcpServer`
Save or update an MCP server configuration:
```graphql
mutation SaveServer(
  $name: String!
  $transport: String!
  $url: String
  $command: String
  $argsJson: String
  $headersJson: String
  $queryParamsJson: String
) {
  saveMcpServer(
    name: $name
    transport: $transport
    url: $url
    command: $command
    argsJson: $argsJson
    headersJson: $headersJson
    queryParamsJson: $queryParamsJson
  ) {
    name
    transport
    url
    command
    argsJson
    enabled
  }
}
```

**Variables:**
```json
{
  "name": "my-server",
  "transport": "stdio",
  "command": "python",
  "argsJson": "[\"server.py\"]"
}
```

**Response:**
```json
{
  "data": {
    "saveMcpServer": {
      "name": "my-server",
      "transport": "stdio",
      "url": null,
      "command": "python",
      "argsJson": "[\"server.py\"]",
      "enabled": true
    }
  }
}
```

#### `connectMcpServer(name: String!)`
Connect to an MCP server:
```graphql
mutation ConnectServer($serverName: String!) {
  connectMcpServer(name: $serverName) {
    success
    message
    tools {
      name
      description
      schema
    }
  }
}
```

**Variables:**
```json
{
  "serverName": "my-server"
}
```

**Response:**
```json
{
  "data": {
    "connectMcpServer": {
      "success": true,
      "message": "Successfully connected to my-server",
      "tools": [
        {
          "name": "get_weather",
          "description": "Get current weather information",
          "schema": "{\"type\":\"object\",\"properties\":{\"location\":{\"type\":\"string\"}}}"
        }
      ],
      "serverName": "my-server",
      "connectionStatus": "CONNECTED"
    }
  }
}
```

#### `disconnectMcpServer(name: String!)`
Disconnect from an MCP server:
```graphql
mutation DisconnectServer($serverName: String!) {
  disconnectMcpServer(name: $serverName) {
    success
    message
  }
}
```

**Variables:**
```json
{
  "serverName": "my-server"
}
```

**Response:**
```json
{
  "data": {
    "disconnectMcpServer": {
      "success": true,
      "message": "Disconnected successfully"
    }
  }
}
```

#### `setMcpServerEnabled(name: String!, enabled: Boolean!)`
Enable or disable an MCP server:
```graphql
mutation SetServerEnabled($serverName: String!, $enabled: Boolean!) {
  setMcpServerEnabled(name: $serverName, enabled: $enabled) {
    name
    transport
    url
    command
    argsJson
    enabled
  }
}
```

**Variables:**
```json
{
  "serverName": "my-server",
  "enabled": false
}
```

**Response:**
```json
{
  "data": {
    "setMcpServerEnabled": {
      "name": "my-server",
      "transport": "stdio",
      "url": null,
      "command": "python",
      "argsJson": "[\"server.py\"]",
      "enabled": false
    }
  }
}
```

#### `removeMcpServer(name: String!)`
Remove an MCP server:
```graphql
mutation RemoveServer($serverName: String!) {
  removeMcpServer(name: $serverName)
}
```

**Variables:**
```json
{
  "serverName": "my-server"
}
```

**Response:**
```json
{
  "data": {
    "removeMcpServer": true
  }
}
```

## Complete Example Workflow

### 1. Save Server Configuration
```graphql
mutation {
  saveMcpServer(
    name: "weather-server"
    transport: "stdio"
    command: "python"
    argsJson: "[\"weather_server.py\"]"
  ) {
    name
    transport
    enabled
  }
}
```

### 2. Check Server Health
```graphql
query {
  mcpServerHealth(name: "weather-server") {
    status
    tools {
      name
      description
    }
  }
}
```

### 3. Connect to Server
```graphql
mutation {
  connectMcpServer(name: "weather-server") {
    success
    message
    tools {
      name
      description
      schema
    }
  }
}
```

### 4. List All Servers with Connection Status
```graphql
query {
  mcpServers {
    name
    transport
    enabled
    connectionStatus
    connectedAt
    toolCount
    tools {
      name
      description
    }
  }
}
```

### 5. Disconnect from Server
```graphql
mutation {
  disconnectMcpServer(name: "weather-server") {
    success
    message
  }
}
```

## Python API

### Manager Methods

#### `connect_server(name: str) -> Tuple[bool, str, List[Dict]]`
Connects to a server and returns (success, message, tools):
```python
success, message, tools = await mcp.connect_server("my-server")
if success:
    print(f"Connected! Found {len(tools)} tools")
    for tool in tools:
        print(f"- {tool['name']}: {tool['description']}")
else:
    print(f"Connection failed: {message}")
```

#### `disconnect_server(name: str) -> Tuple[bool, str]`
Disconnects from a server:
```python
success, message = await mcp.disconnect_server("my-server")
print(f"Disconnect: {message}")
```



#### `acheck_server_health(name: str) -> Tuple[str, List[Dict]]`
Check server health and get available tools:
```python
status, tools = await mcp.acheck_server_health("my-server")
print(f"Status: {status}")
for tool in tools:
    print(f"- {tool['name']}: {tool['description']}")
```

## Usage Example

```python
import asyncio
from app.mcp.manager import mcp

async def example():
    # Connect to a server
    success, message, tools = await mcp.connect_server("my-mcp-server")
    if success:
        print(f"Connected successfully! Found {len(tools)} tools")
        
        # Get all servers with connection status
        servers = await mcp.alist_servers()
        connected_servers = [s.name for s in servers if s.connection_status == "CONNECTED"]
        print(f"Connected servers: {connected_servers}")
        
        # Tools are already available from the connection response
        print(f"Tools available from connection: {len(tools)}")
        
        # Disconnect when done
        await mcp.disconnect_server("my-mcp-server")
    else:
        print(f"Connection failed: {message}")

# Run the example
asyncio.run(example())
```

## Testing

Run the test script to verify functionality:
```bash
python test_mcp_connections.py
```

## Implementation Details

### Connection Flow
1. **Health Check**: Verify server is healthy using `acheck_server_health`
2. **Configuration**: Build adapter map for the specific server
3. **Client Creation**: Create MultiServerMCPClient for the server
4. **Tool Discovery**: Fetch tools from the server with timeout
5. **Storage**: Store connection info in `connected_servers` dict

### Disconnection Flow
1. **Client Cleanup**: Close client connection if close method exists
2. **Map Removal**: Remove server from `connected_servers` dict
3. **Resource Cleanup**: Free up memory and resources

### Error Handling
- **Timeout**: 8-second timeout for connections, 5-second for health checks
- **Network Errors**: Graceful handling of connection failures
- **Invalid Servers**: Proper error messages for non-existent servers
- **Disabled Servers**: Prevention of connecting to disabled servers

## Benefits

1. **Granular Control**: Connect/disconnect individual servers as needed
2. **Resource Management**: Better memory and connection management
3. **Tool Discovery**: Access to detailed tool information
4. **Health Monitoring**: Built-in health checks before connections
5. **GraphQL Integration**: Full GraphQL API support for all operations
