# Django CopilotKit Assistant

A Django application that integrates CopilotKit with LangGraph agents for AI-powered assistance.

## Features

- 🤖 AI-powered chat agent using LangGraph
- 🔍 Web search capabilities with Tavily
- ⏰ Current datetime tool
- 🌐 RESTful API endpoints
- 🔄 Streaming responses
- 🔐 Google OAuth authentication with NextAuth.js integration
- 📊 GraphQL API for MCP server management
- 👥 User-specific and public MCP server support
- 🔧 MCP server connection management with health monitoring

## Prerequisites

- Python 3.12
- Virtual environment (recommended)
- API keys for the services you want to use

## Setup

1. **Clone and navigate to the project:**
   ```bash
   cd assistant
   ```

2. **Create your virtual environment:**
   ```bash
   # Windows
   py -m venv env
   # Windows (if you have more than one python version installed, create virtual environment using specific verion)
   py -3.12 -m venv env
   
   # macOS/Linux
   source env/bin/activate
   ```
3. **Activate your virtual environment:**
   ```bash
   # Windows
   env\Scripts\activate
   
   # macOS/Linux
   source env/bin/activate
   ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Set up environment variables:**
   
   
   **Create a .env file:**
   ```bash
   # Create .env file with your API keys
   DEEPSEEK_API_KEY=your_deepseek_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here
   TAVILY_API_KEY=your_tavily_api_key_here
   GOOGLE_CLIENT_ID=your_google_client_id_here
   DEBUG=True
   SECRET_KEY=your_django_secret_key
   ```

6. **Run database migrations (Optional):**
   ```bash
   python manage.py migrate
   ```

7. **Start the server:**
   ```bash
   uvicorn assistant.asgi:application --reload
   ```

## API Endpoints

### CopilotKit Endpoints

- `GET/POST /api/copilotkit/info` - Get agent information
- `POST /api/copilotkit/agent/{name}` - Execute an agent
- `POST /api/copilotkit/agent/{name}/state` - Get agent state
- `POST /api/copilotkit/action/{name}` - Execute an action

### GraphQL API

The application provides a GraphQL API for managing MCP servers and user authentication.

#### Authentication

**Authentication Method**: Google OAuth with Bearer Token
- Include `Authorization: Bearer <google_id_token>` header in GraphQL requests
- The middleware automatically validates the token and creates/retrieves the user

#### Queries

**`mcp_servers`** - Get all public MCP servers with Strawberry Django filtering
```graphql
query {
  mcpServers(
    filters: {
      transport: { exact: "sse" }
      enabled: { exact: true }
      connectionStatus: { exact: "CONNECTED" }
      requiresOauth2: { exact: false }
    }
  ) {
    id
    name
    transport
    url
    command
    args
    enabled
    requiresOauth2
    connectionStatus
    tools {
      name
      description
      schema
    }
    updatedAt
    owner
    isPublic
  }
}
```

**Advanced Filtering Examples:**

**Filter by name containing "test":**
```graphql
query {
  mcpServers(
    filters: {
      name: { contains: "test" }
    }
  ) {
    name
    transport
  }
}
```

**Filter with OR conditions:**
```graphql
query {
  mcpServers(
    filters: {
      OR: [
        { transport: { exact: "sse" } }
        { transport: { exact: "stdio" } }
      ]
    }
  ) {
    name
    transport
  }
}
```

**Filter by enabled servers that don't require OAuth2:**
```graphql
query {
  mcpServers(
    filters: {
      enabled: { exact: true }
      requiresOauth2: { exact: false }
    }
  ) {
    name
    enabled
    requiresOauth2
  }
}
```

**Available Filter Lookups:**
- `exact`: Exact match
- `contains`: Contains substring
- `iContains`: Case-insensitive contains
- `startsWith`: Starts with string
- `endsWith`: Ends with string
- `inList`: Value in list
- `isNull`: Check for null values
- `AND`, `OR`, `NOT`: Logical operators

**`getUserMcpServers`** - Get user's own MCP servers (requires authentication)
```graphql
query {
  getUserMcpServers {
    id
    name
    transport
    url
    command
    args
    enabled
    requiresOauth2
    connectionStatus
    tools {
      name
      description
      schema
    }
    updatedAt
    owner
    isPublic
  }
}
```

**`mcpServerHealth`** - Check server health status
```graphql
query {
  mcpServerHealth(name: "server_name") {
    status
    tools {
      name
      description
      schema
    }
  }
}
```

**`me`** - Get current user information (requires authentication)
```graphql
query {
  me {
    id
    email
    emailVerified
    name
    picture
    provider
  }
}
```

#### Mutations

**`saveMcpServer`** - Create or update an MCP server (requires authentication)
```graphql
mutation {
  saveMcpServer(
    name: "my_server"
    transport: "sse"
    url: "https://example.com/mcp"
    isPublic: false
  ) {
    id
    name
    transport
    url
    enabled
    owner
    isPublic
  }
}
```

**`removeMcpServer`** - Remove user's own MCP server (requires authentication)
```graphql
mutation {
  removeMcpServer(name: "my_server")
}
```

**`setMcpServerEnabled`** - Enable/disable an MCP server
```graphql
mutation {
  setMcpServerEnabled(name: "my_server", enabled: true) {
    id
    name
    enabled
  }
}
```

**`connectMcpServer`** - Connect to an MCP server
```graphql
mutation {
  connectMcpServer(name: "my_server") {
    success
    message
    serverName
    connectionStatus
    tools {
      name
      description
      schema
    }
  }
}
```

**`disconnectMcpServer`** - Disconnect from an MCP server
```graphql
mutation {
  disconnectMcpServer(name: "my_server") {
    success
    message
  }
}
```

**`restartMcpServer`** - Restart an MCP server connection
```graphql
mutation {
  restartMcpServer(name: "my_server") {
    success
    message
    serverName
    connectionStatus
    tools {
      name
      description
      schema
    }
  }
}
```

### Utility Endpoints

- `GET /api/health` - Health check
- `POST /api/echo` - Echo message (for testing)

## Usage Examples

### Test the info endpoint:
```bash
curl -X POST http://localhost:8000/api/copilotkit/info
```

### Test the health endpoint:
```bash
curl http://localhost:8000/api/health
```

### GraphQL Examples

**Test GraphQL endpoint:**
```bash
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ mcpServers { name transport url enabled } }"}'
```

**Authenticated GraphQL request:**
```bash
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN" \
  -d '{"query": "{ me { id email name } }"}'
```

## Authentication Setup

### Google OAuth Configuration

1. **Create a Google Cloud Project:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing one

2. **Enable Google+ API:**
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google+ API" and enable it

3. **Create OAuth 2.0 Credentials:**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client IDs"
   - Set application type to "Web application"
   - Add authorized redirect URIs for your frontend

4. **Configure Environment:**
   - Add `GOOGLE_CLIENT_ID` to your `.env` file
   - Use the client ID from your Google Cloud project

### Frontend Integration (NextAuth.js)

The backend is designed to work with NextAuth.js on the frontend. The frontend should:

1. Configure NextAuth.js with Google provider
2. Send the Google ID token in the `Authorization: Bearer <token>` header
3. Handle token refresh when tokens expire

## MCP Server Management

### Server Types

- **Shared Servers**: Available to all users (public)
- **User Servers**: Private servers owned by individual users

### Server Ownership

- Users can only modify/delete their own servers
- Shared servers are read-only for regular users
- Server names must be unique per user (for private servers)
- Server names must be unique globally (for public servers)

### Connection Management

- Servers can be connected/disconnected dynamically
- Health monitoring provides real-time status
- OAuth2 authentication supported for protected servers
- Automatic tool discovery and schema validation

## Troubleshooting

### 500 Internal Server Error

If you're getting 500 errors, check:

1. **API Keys**: Make sure your API keys are set in the `.env` file
2. **Environment Variables**: Verify the `.env` file is being loaded
3. **Dependencies**: Ensure all packages are installed correctly

### Common Issues

- **Missing API Keys**: The application will show helpful error messages if API keys are missing
- **Network Issues**: Make sure you have internet access for API calls
- **Port Conflicts**: If port 8000 is busy, use a different port: `uvicorn assistant.asgi:application --host 0.0.0.0 --port 8001 --reload`

## Development

### Project Structure

```
assistant/
├── app/
│   ├── agent.py          # LangGraph agent definition
│   ├── chat.py           # Chat node implementation
│   ├── copilotkit_integration.py  # Django-CopilotKit integration
│   ├── model.py          # LLM configuration
│   ├── schema.py         # Agent state schema
│   ├── sdk.py            # CopilotKit SDK setup (define your agent here)
│   └── views.py          # Django views
├── assistant/
│   ├── settings.py       # Django settings
│   └── urls.py           # Main URL configuration
├── manage.py             # Django management script
├── requirements.txt      # Python dependencies
└── setup_env.py          # Environment setup script
```

### Adding New Tools

To add new tools to the agent:

1. Define the tool in `app/chat.py`
2. Add it to the `tools` list in the `get_tools` function
3. Update the system message if needed

### Adding New Agents

To add new agents:

1. Create a new graph in `app/agent.py`
2. Add the agent to the SDK configuration in `app/sdk.py`
3. Update the URL patterns if needed

