# MCP Module Documentation

Multi-tenant MCP (Model Context Protocol) server management with Redis-based session isolation for LangChain integration.

---

## What Is This Module?

This module allows your Django application to:
1. **Manage multiple MCP servers** (GitHub, Slack, custom APIs, etc.)
2. **Organize servers with categories** (Productivity, Development, Data & Analytics, etc.)
3. **Connect/disconnect** to servers per user session
4. **Retrieve tools** from connected servers for LangChain agents
5. **Isolate state** so different users don't see each other's connections
6. **Handle OAuth** for servers that require authentication

**Real-world example:** User A connects to GitHub MCP server in the "Development" category. User B shouldn't see User A's connection or access User A's GitHub tools. This module ensures complete isolation.

---

## Core Components

### 0. Models (`models.py`)

**What it does:** Defines database models for MCP servers and categories.

**Why it exists:** Structured data storage with relationships and constraints.

**Key Models:**

#### MCPServer Model
- Custom ID with `mcp_` prefix (e.g., `mcp_abc123xyz`)
- Supports multiple transports: stdio, SSE, WebSocket, streamable_http
- User ownership (private servers) and public servers
- Category relationship (optional, nullable)
- OAuth2 support flag
- Connection status tracking

#### Category Model
- Custom ID with `ctg_` prefix (e.g., `ctg_abc123xyz`) - Stripe-style professional naming
- Visual metadata: `name`, `icon` (URL/emoji), `color` (hex/rgb), `description`
- Related servers via `servers` reverse relation
- Auto-generated timestamps
- Unique names enforced at database level

**Example:**
```python
category = Category.objects.create(
    name="Productivity",
    icon="🚀",
    color="#4CAF50",
    description="Productivity tools"
)
# ID auto-generated: ctg_k3j5h2n4

server = MCPServer.objects.create(
    name="GitHub MCP",
    transport="stdio",
    category=category,
    owner=user
)
# ID auto-generated: mcp_abc123xyz
```

---

### 1. MCPServerManager (`manager.py`)

**What it does:** Orchestrates all MCP server operations - like a traffic controller for server connections.

**Why it exists:** You need one central place to manage server lifecycles, connections, and tool retrieval. Without this, you'd have scattered logic throughout your app.

**Purpose:**
- Manage server configurations (CRUD operations)
- Handle connect/disconnect requests
- Fetch tools for LangChain agents
- Ensure session isolation (User A can't see User B's connections)

#### Key Methods Explained

##### Server Management Methods

```python
await mcp.asave_server(
    name,
    transport,
    owner,
    url=...,
    requires_oauth2=...,
    category_id="ctg_abc123"
)
```
**Purpose:** Save or update an MCP server configuration in the database.

**Why you'd use it:** When a user adds a new MCP server (e.g., "Add my custom API server").

**What it does:**
- Creates or updates MCPServer record in database
- Stores configuration (URL, transport type, OAuth requirements)
- Associates server with owner (user)
- Assigns category if `category_id` is provided (optional)

**Example use case:** Admin wants to add a GitHub MCP server in the "Development" category for all users.

---

```python
servers = await mcp.alist_servers(session_id="user_123")
```
**Purpose:** Get all public servers with THIS session's connection status.

**Why you'd use it:** Display available servers in UI with "Connected" or "Disconnected" badges.

**What it does:**
- Fetches all public servers from database
- Enriches each with session-specific connection status from Redis
- Returns list with tools available for connected servers

**Example:** User sees: "GitHub (Connected, 15 tools)", "Slack (Disconnected, 0 tools)"

---

```python
success, message, server = await mcp.connect_server("github", session_id="user_123")
```
**Purpose:** Connect to an MCP server for THIS session only.

**Why you'd use it:** When user clicks "Connect" button on a server card.

**What it does:**
1. Fetches server configuration from database
2. Creates FastMCP client connection
3. Pings server to verify it's alive
4. Fetches available tools from server
5. Stores connection status + tools in Redis (isolated by session_id)
6. Returns success status and server info

**Example:** User connects to GitHub → system fetches available GitHub API tools.

---

```python
success, message, server = await mcp.disconnect_server("github", session_id="user_123")
```
**Purpose:** Disconnect from an MCP server for THIS session.

**Why you'd use it:** When user clicks "Disconnect" or logs out.

**What it does:**
1. Checks if server is connected for this session
2. Updates Redis to mark as DISCONNECTED
3. Removes tools from cache
4. Returns disconnection status

**Important:** Other users' connections are unaffected.

---

```python
tools = await mcp.aget_tools(session_id="user_123")
```
**Purpose:** Get ALL tools from ALL connected servers for THIS session.

**Why you'd use it:** When LangGraph agent needs available tools to execute user requests.

**What it does:**
1. Queries Redis for servers connected in this session
2. Builds adapter map for those servers only
3. Creates throwaway MultiServerMCPClient (doesn't pollute global state)
4. Fetches and returns all tools

**Why throwaway client?** Prevents cross-user tool leakage. Each session gets fresh, isolated tools.

**Example:** User connected to GitHub + Slack → agent gets tools from both.

---

##### Internal Helper Methods

```python
async def _build_adapter_map(self, names)
```
**Purpose:** Delegate adapter building to `MCPAdapterBuilder`.

**Why it's separate:** Manager shouldn't know HOW to build configs, just WHAT to build.

**What it does:** Calls `_adapter_builder.build_adapter_map()` and returns result.

---

```python
async def _get_connection_status(self, server_name, session_id)
```
**Purpose:** Check if a server is connected for THIS session.

**Why it's needed:** Redis holds session-isolated state. This fetches it.

**What it does:** Calls Redis manager to get status: "CONNECTED", "DISCONNECTED", or "FAILED".

---

```python
async def _set_connection_status(self, server_name, status, tools, session_id)
```
**Purpose:** Update connection state in Redis for THIS session.

**Why it's needed:** Keep session state synchronized.

**What it does:** Stores status + tools in Redis with TTL (auto-expires after 24 hours).

---

### 2. MCPAdapterBuilder (`adapter_builder.py`)

**What it does:** Converts database server records into LangChain adapter configurations.

**Why it exists:** LangChain's `MultiServerMCPClient` needs a specific config format. This class handles the conversion.

**Purpose:**
- Transform MCPServer model → LangChain adapter format
- Handle different transport types (stdio, SSE, WebSocket)
- Merge URL query parameters
- Inject OAuth tokens into headers

**Analogy:** Like a translator converting your database format into LangChain's expected format.

#### Key Methods Explained

```python
adapter_map = await builder.build_adapter_map(["github", "slack"])
```
**Purpose:** Build adapter configs for specified servers.

**Why you'd use it:** When initializing LangChain MultiServerMCPClient.

**What it does:**
1. Queries database for enabled servers matching names
2. Routes each server to appropriate builder (stdio vs network)
3. Returns dictionary mapping server name → config

**Output example:**
```python
{
    "github": {
        "url": "https://api.github.com/mcp",
        "transport": "sse",
        "headers": {"Authorization": "Bearer token123"}
    },
    "local-server": {
        "command": "python",
        "args": ["server.py"],
        "transport": "stdio"
    }
}
```

**Why this format?** LangChain's MultiServerMCPClient requires it to know how to connect.

---

```python
url = builder.build_server_url(server)
```
**Purpose:** Construct complete URL with merged query parameters.

**Why you'd use it:** Server might have base URL + additional query params stored separately.

**What it does:**
1. Takes base URL from server.url
2. Merges existing query params with server.query_params
3. Returns complete URL string

**Example:**
- Input: `url="https://api.com?foo=1"`, `query_params={"bar": "2"}`
- Output: `"https://api.com?foo=1&bar=2"`

**Why merge?** Some servers need dynamic parameters (API keys, filters) added to base URL.

---

```python
entry = await builder.add_oauth_headers(entry, server)
```
**Purpose:** Add OAuth authorization token to adapter config.

**Why you'd use it:** Server requires OAuth authentication.

**What it does:**
1. Fetches stored OAuth tokens from file storage
2. Adds "Authorization: Bearer {token}" header to config
3. Returns updated config

**Why separate method?** Not all servers need OAuth. This keeps logic clean.

---

```python
adapter = builder._build_stdio_adapter(server)
```
**Purpose:** Build config for stdio (local process) transport.

**Why stdio?** Some MCP servers run as local processes (like Python scripts).

**What it does:**
```python
{
    "command": "python",
    "args": ["mcp_server.py", "--port", "8080"],
    "transport": "stdio"
}
```

**Example use case:** Running a local MCP server for development.

---

```python
adapter = await builder._build_network_adapter(server)
```
**Purpose:** Build config for network transports (SSE, WebSocket, HTTP).

**Why network?** Most production MCP servers are remote APIs.

**What it does:**
1. Builds complete URL with query params
2. Adds headers from database
3. Injects OAuth token if required
4. Returns network adapter config

**Example output:**
```python
{
    "url": "https://api.github.com/mcp?version=2",
    "transport": "sse",
    "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer ghp_xxxx"
    }
}
```

---

### 3. MCPRedisManager (`redis_manager.py`)

**What it does:** Manages all Redis operations for session-isolated connection state.

**Why it exists:** You need fast, temporary storage for connection states that automatically expire. Database is too slow; Redis is perfect.

**Purpose:**
- Store which servers are connected per session
- Cache tools for each connection
- Automatically clean up expired sessions (TTL)
- Provide fast connection status lookups

**Analogy:** Like sticky notes that auto-delete after 24 hours.

#### Key Methods Explained

```python
status = await mcp_redis.get_connection_status("github", "user_123")
```
**Purpose:** Check if server is connected for this session.

**Why you'd use it:** Before showing "Connected" badge in UI.

**What it does:**
- Looks up Redis key: `mcp:session:user_123:server:github:status`
- Returns "CONNECTED", "DISCONNECTED", or "FAILED"

**Why Redis?** Fast lookups (microseconds) vs database queries (milliseconds).

---

```python
await mcp_redis.set_connection_status("github", "CONNECTED", tools, "user_123")
```
**Purpose:** Update connection state and cache tools.

**Why you'd use it:** After successfully connecting to a server.

**What it does:**
1. Stores status in Redis with 24-hour TTL
2. Caches tools JSON for fast retrieval
3. Adds server to session's connections set
4. Stores connection timestamp

**Why TTL?** Connections auto-expire if user doesn't return. Prevents stale data.

---

```python
tools = await mcp_redis.get_connection_tools("github", "user_123")
```
**Purpose:** Retrieve cached tools for a connection.

**Why you'd use it:** Display available tools without re-fetching from server.

**What it does:**
- Fetches tools JSON from Redis
- Deserializes to Python list
- Returns tool dictionaries

**Performance benefit:** Instant vs potentially slow server API call.

---

```python
servers = await mcp_redis.get_connected_servers("user_123")
```
**Purpose:** Get list of all servers connected in this session.

**Why you'd use it:** Building adapter map for LangChain client.

**What it does:**
- Queries Redis set: `mcp:session:user_123:connections`
- Returns list of server names: `["github", "slack"]`

**Why a set?** Efficient membership testing and no duplicates.

---

```python
await mcp_redis.clear_session_data("user_123")
```
**Purpose:** Delete all connection data for a session.

**Why you'd use it:** User logs out or session expires.

**What it does:**
1. Finds all keys matching pattern: `mcp:session:user_123:*`
2. Deletes all matching keys using SCAN (memory-efficient)
3. Frees up Redis memory

**Why SCAN?** Handles large key sets without blocking Redis.

---

```python
is_healthy = await mcp_redis.health_check()
```
**Purpose:** Verify Redis connection is working.

**Why you'd use it:** Health check endpoint for monitoring/alerting.

**What it does:**
- Pings Redis
- Returns True if successful, False otherwise

**Example:** Kubernetes liveness probe calls this.

---

### 4. Utilities (`utils.py`)

**What it does:** Shared helper functions used across the module.

**Why it exists:** DRY (Don't Repeat Yourself) - avoid duplicating code.

**Purpose:** Provide reusable utilities for tool serialization, schema patching, and session key generation.

#### Key Functions Explained

```python
safe_json_dumps(obj)
```
**Purpose:** Safely convert Python object to JSON string.

**Why you'd use it:** When storing tools in Redis (needs JSON).

**What it does:**
- Attempts JSON serialization
- Handles non-serializable types (functions, custom objects)
- Returns "{}" if serialization fails

**Why needed?** Tool objects may have complex types that break standard `json.dumps()`.

---

```python
tools = patch_tools_schema(tools)
```
**Purpose:** Ensure all tools have valid schemas for OpenAI function calling.

**Why you'd use it:** OpenAI requires specific schema format for function calls.

**What it does:**
- Checks each tool's `args_schema`
- Adds `EmptyArgsSchema` if missing or invalid
- Returns patched tools

**Why important?** Invalid schemas break LangChain's OpenAI integration.

---

```python
tools_info = serialize_tools(tools)
```
**Purpose:** Convert tool objects to JSON-serializable dictionaries.

**Why you'd use it:** GraphQL needs plain dicts, not Python objects.

**What it does:**
- Extracts name, description, schema from each tool
- Handles both FastMCP and LangChain tool formats
- Returns list of dicts

**Example output:**
```python
[
    {
        "name": "search_github",
        "description": "Search GitHub repositories",
        "schema": '{"type": "object", "properties": {...}}'
    }
]
```

---

```python
session_key = generate_anonymous_session_key(request)
```
**Purpose:** Create unique session ID for anonymous users.

**Why you'd use it:** Anonymous users need session isolation too.

**What it does:**
- Extracts IP, user agent, forwarded headers
- Creates hash: `"anon_{hash(ip_useragent_forwarded)}"`
- Returns consistent key for same anonymous user

**Why hash?** Same anonymous user gets same session across requests.

---

### 5. OAuth Storage (`oauth_storage.py`)

**What it does:** User-isolated OAuth token storage.

**Why it exists:** Prevent token sharing between users (security issue).

**Purpose:** Each user/session gets their own OAuth token file, not a shared one.

#### Key Classes Explained

```python
storage = ClientTokenStorage(server_url, user_id, session_id)
```
**Purpose:** Store OAuth tokens in user-specific directory.

**Why you'd use it:** When server requires OAuth authentication.

**What it does:**
- Creates directory: `cache_dir/user_{user_id}/`
- Stores tokens isolated per user
- Prevents User A seeing User B's tokens

**Security benefit:** Token isolation prevents unauthorized access.

---

```python
oauth = ClientOAuth(mcp_url, user_id, session_id, client_name, callback_port, scopes)
```
**Purpose:** OAuth client with user-isolated token storage.

**Why you'd use it:** Connecting to OAuth-protected MCP servers.

**What it does:**
1. Initiates OAuth flow
2. Stores tokens in user-specific cache
3. Auto-refreshes tokens when expired

**Example:** GitHub MCP requires OAuth → this handles the flow.

---

### 6. Category Schema (`category_schema.py`)

**What it does:** GraphQL queries and mutations for category management.

**Why it exists:** Separate schema for category operations keeps code organized.

**Purpose:** Provide CRUD operations for categories via GraphQL API.

#### Key Operations

**Queries:**

```graphql
# Get all categories
query {
  categories {
    edges {
      node {
        id
        name
        icon
        color
        description
      }
    }
  }
}

# Get categories with their servers
query {
  categories {
    edges {
      node {
        name
        servers {
          id
          name
        }
      }
    }
  }
}

# Get single category
query {
  category(id: "ctg_abc123") {
    name
    icon
    servers {
      name
    }
  }
}
```

**Mutations:**

```graphql
# Create category
mutation {
  createCategory(
    name: "Productivity"
    icon: "🚀"
    color: "#4CAF50"
    description: "Productivity tools"
  ) {
    id
    name
  }
}

# Update category
mutation {
  updateCategory(
    id: "ctg_abc123"
    color: "#FF5722"
  ) {
    id
    name
    color
  }
}

# Delete category
mutation {
  deleteCategory(id: "ctg_abc123")
}
```

**Why separate schema?** Keeps MCP server logic separate from category management. Clean separation of concerns.

---

### 7. Constants (`constants.py`)

**What it does:** Centralizes all configuration values.

**Why it exists:** Change timeouts/TTLs in ONE place, not scattered throughout code.

**Purpose:** Make configuration easy to adjust without touching business logic.

**Key constants:**
- `REDIS_CONNECTION_TTL = 86400` - How long connections live (24 hours)
- `MCP_CLIENT_TIMEOUT = 30.0` - Server ping timeout
- `TOOL_FETCH_TIMEOUT = 30.0` - Tool retrieval timeout
- `OAUTH_CLIENT_NAME = "Inspect MCP"` - OAuth client identifier
- `STATUS_CONNECTED = "CONNECTED"` - Connection status constant

**Why constants?** No magic numbers. Easy to adjust. Clear intent.

---

## How It All Works Together

### Example: User Connects to GitHub MCP Server

```
1. User clicks "Connect to GitHub" in UI
   ↓
2. GraphQL mutation: connectMcpServer(name: "github")
   ↓
3. mcp_schema.py extracts session_id from request
   ↓
4. Calls: mcp.connect_server("github", session_id="user_123")
   ↓
5. MCPServerManager:
   - Fetches GitHub server config from database
   - Sees requires_oauth2=true
   - Creates ClientOAuth with user-specific storage
   ↓
6. FastMCP client connects to GitHub server
   - Pings server (verifies alive)
   - Fetches available tools (search_repos, create_issue, etc.)
   ↓
7. MCPServerManager:
   - Patches tool schemas (ensures OpenAI compatibility)
   - Serializes tools to JSON dicts
   ↓
8. Stores in Redis via MCPRedisManager:
   - mcp:session:user_123:server:github:status = "CONNECTED"
   - mcp:session:user_123:server:github:tools = [tools JSON]
   - Adds "github" to mcp:session:user_123:connections set
   ↓
9. Returns success + server with tools to GraphQL
   ↓
10. UI shows: "GitHub (Connected, 15 tools)"
```

### Example: LangGraph Agent Needs Tools

```
1. Agent starts to process user request
   ↓
2. Calls: tools = await mcp.aget_tools(session_id="user_123")
   ↓
3. MCPServerManager:
   - Queries Redis: which servers are connected for user_123?
   - Gets: ["github", "slack"]
   ↓
4. Calls: adapter_map = await _adapter_builder.build_adapter_map(["github", "slack"])
   ↓
5. MCPAdapterBuilder:
   - Fetches GitHub + Slack configs from database
   - Builds network adapters (URLs, headers, OAuth tokens)
   - Returns adapter map
   ↓
6. MCPServerManager:
   - Creates throwaway MultiServerMCPClient(adapter_map)
   - Fetches tools from GitHub + Slack servers
   - Patches schemas, returns tools
   ↓
7. Agent receives tools and can now execute them
```

---

## Key Design Decisions

### Why Session Isolation?
**Problem:** Multi-tenant app. User A's connections shouldn't affect User B.

**Solution:** All Redis keys include `session_id`. Each user has separate state.

### Why Module-Level Singleton for Builder?
**Problem:** Builder is stateless (no changing data).

**Solution:** One instance for entire app. Efficient, no overhead.

### Why Separate Builder from Manager?
**Problem:** Manager was doing too much (500+ lines).

**Solution:** Extract adapter building. Cleaner, testable, reusable.

### Why Redis TTL?
**Problem:** Stale connections accumulate, waste memory.

**Solution:** Auto-expire after 24 hours. Prevents cleanup code.

### Why Throwaway Client in aget_tools()?
**Problem:** Global client causes cross-user tool leakage.

**Solution:** Build fresh client per session. Isolated, safe.

---

## Common Operations

### Create a Category
```python
category = await Category.objects.acreate(
    name="Communication",
    icon="💬",
    color="#9C27B0",
    description="Chat and collaboration tools"
)
# Returns: Category with id="ctg_abc123xyz"
```

### Add a New MCP Server (with Category)
```python
await mcp.asave_server(
    name="slack",
    transport="sse",
    owner=user,
    url="https://slack.com/api/mcp",
    requires_oauth2=True,
    is_public=True,
    category_id="ctg_abc123xyz"  # Optional category assignment
)
```

### Connect User to Server
```python
success, msg, server = await mcp.connect_server("slack", session_id=user.username)
if success:
    print(f"Connected! {len(server.tools)} tools available")
```

### Get Tools for Agent
```python
tools = await mcp.aget_tools(session_id=user.username)
# Pass to LangGraph agent
```

### Clean Up on Logout
```python
await mcp_redis.disconnect_all_servers(session_id=user.username)
await mcp_redis.clear_session_data(session_id=user.username)
```

---

## Troubleshooting

### "Server not connected"
**Cause:** Connection expired or failed.
**Fix:** Check Redis TTL, verify server is reachable, reconnect.

### "No tools available"
**Cause:** Server connected but tools not cached.
**Fix:** Check Redis, verify server returns tools, reconnect.

### "Cross-user contamination"
**Cause:** Not passing session_id consistently.
**Fix:** Always include session_id in all operations.

---

## Summary

This module provides:
- ✅ **Multi-tenant MCP server management**
- ✅ **Category-based organization** with visual metadata (icons, colors)
- ✅ **Session-isolated connection state**
- ✅ **Redis-backed fast lookups**
- ✅ **OAuth support with user isolation**
- ✅ **LangChain integration via adapters**
- ✅ **Professional ID patterns** (`mcp_*`, `ctg_*`)
- ✅ **Clean separation of concerns**

Each component has a specific job, and they work together to provide secure, efficient MCP server management with organized categorization for LangGraph agents.
