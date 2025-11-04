# MCP Hub - Backend

Django 5.2 backend for the MCP (Model Context Protocol) Hub. Provides GraphQL API for managing MCP servers, categories, and AI-powered chat using LangGraph agents with CopilotKit integration.

## Tech Stack

- **Framework:** Django 5.2 (Python 3.12)
- **API:** GraphQL with Strawberry Django
- **Database:** SQLite (PostgreSQL-ready)
- **Cache:** Redis (connection state management)
- **AI:** LangGraph agents, OpenAI/DeepSeek
- **Chat:** CopilotKit integration
- **Auth:** Google OAuth (token validation)

## Features

- 🔧 **MCP Server Management** - CRUD operations with user ownership
- 📂 **Category System** - Organize servers with icons and colors
- 🤖 **AI Chat Agent** - LangGraph with dynamic tool binding
- 🔐 **Authentication** - Google OAuth with NextAuth.js integration
- 📊 **GraphQL API** - Advanced filtering, pagination, relay support
- 🔄 **Redis State** - Connection state with 24hr TTL
- 🌐 **Multi-transport** - stdio, SSE, WebSocket, HTTP streaming

## Prerequisites

- Python 3.12+
- Redis server running
- Google OAuth credentials
- API keys (OpenAI/DeepSeek, Tavily for web search)

## Quick Start

### 1. Installation

```bash
# Using uv (recommended)
cd mcp-hub
uv venv
uv pip install -r requirements.txt

# Or using pip
python -m venv env
env\Scripts\activate  # Windows
source env/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 2. Environment Variables

Create `.env` file:

```bash
SECRET_KEY=your_django_secret_key
DEBUG=True
ALLOWED_HOSTS=localhost
GOOGLE_CLIENT_ID=your_google_client_id
OPENAI_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key  # Optional
TAVILY_API_KEY=your_tavily_api_key  # Optional for web search
REDIS_URL=redis://localhost:6379/0
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### 3. Database Setup

```bash
uv run manage.py migrate
```

### 4. Seed Categories (Optional)

```bash
uv run python seed_categories.py
```

This creates 11 default categories: Productivity, Development, Data & Analytics, Communication, AI & Machine Learning, Cloud & Infrastructure, Database, Security, APIs & Integration, Content & Media, and Other.

### 5. Start Server

```bash
uv run uvicorn assistant.asgi:application --reload
```

Server runs at `http://localhost:8000`

## Project Structure

```
mcp-hub/
├── app/
│   ├── mcp/                    # MCP server management
│   │   ├── models.py           # MCPServer & Category models
│   │   ├── manager.py          # MCP manager singleton
│   │   ├── mcp_schema.py       # MCP GraphQL operations
│   │   ├── category_schema.py  # Category GraphQL operations
│   │   ├── types.py            # Strawberry types & filters
│   │   ├── adapter_builder.py  # Transport adapters
│   │   └── redis_manager.py    # Connection state management
│   ├── agent/                  # LangGraph agents
│   │   ├── chat.py             # Chat node with tool binding
│   │   ├── model.py            # LLM configuration
│   │   └── agent.py            # Agent graph definition
│   ├── auth/                   # Authentication
│   │   ├── middleware.py       # Google OAuth middleware
│   │   └── schema.py           # Auth GraphQL queries
│   ├── graphql/                # GraphQL root schema
│   │   └── schema.py           # Combines all schemas
│   └── admin.py                # Django admin config
├── assistant/                  # Django project settings
├── seed_categories.py          # Category seeding script
└── manage.py                   # Django CLI
```

## GraphQL API

### Endpoints

- **GraphQL:** `http://localhost:8000/graphql`
- **GraphiQL:** `http://localhost:8000/graphql` (interactive explorer)
- **Health:** `http://localhost:8000/api/health`

### Authentication

Include Google ID token for authenticated requests:
```
Authorization: Bearer <google_id_token>
```

### Key Queries

**Get all servers with categories:**
```graphql
query {
  mcpServers {
    edges {
      node {
        id
        name
        transport
        category {
          id
          name
          icon
          color
        }
        connectionStatus
      }
    }
  }
}
```

**Filter servers by category:**
```graphql
query {
  mcpServers(filters: { category: { name: { exact: "Productivity" } } }) {
    edges {
      node {
        name
        category {
          name
          icon
        }
      }
    }
  }
}
```

**Get all categories with servers:**
```graphql
query {
  categories {
    edges {
      node {
        id
        name
        icon
        color
        servers {
          id
          name
          transport
        }
      }
    }
  }
}
```

### Key Mutations

**Create category:**
```graphql
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
```

**Save server with category:**
```graphql
mutation {
  saveMcpServer(
    name: "GitHub MCP"
    transport: "stdio"
    command: "npx"
    categoryId: "ctg_abc123"
  ) {
    id
    name
    category {
      name
      icon
    }
  }
}
```

**Connect to server:**
```graphql
mutation {
  connectMcpServer(name: "GitHub MCP") {
    success
    message
    connectionStatus
    tools {
      name
      description
    }
  }
}
```

### Advanced Filtering

Strawberry Django supports powerful filtering:

```graphql
query {
  mcpServers(
    filters: {
      AND: [
        { enabled: { exact: true } }
        { transport: { exact: "stdio" } }
        { category: { name: { iContains: "data" } } }
      ]
    }
  ) {
    edges {
      node {
        name
      }
    }
  }
}
```

**Available lookups:** `exact`, `contains`, `iContains`, `startsWith`, `endsWith`, `inList`, `isNull`, `AND`, `OR`, `NOT`

## Key Concepts

### ID Patterns

- **MCP Servers:** `mcp_abc123xyz` (shortuuid)
- **Categories:** `ctg_abc123xyz` (shortuuid with `ctg_` prefix)

### Data Storage

- **Database (SQLite):** Server configs, categories, users
- **Redis (volatile):** Connection state, tools cache (24hr TTL)

### Server Ownership

- **Private servers:** User-owned, only owner can modify
- **Public servers:** Available to all, requires admin to modify
- Server names unique per user (private) or globally (public)

### Transport Types

- **stdio** - Subprocess (command + args)
- **sse** - Server-Sent Events
- **websocket** - WebSocket connection
- **streamable_http** - HTTP streaming

## Development

### Run Migrations

```bash
uv run manage.py makemigrations
uv run manage.py migrate
```

### Django Admin

```bash
uv run manage.py createsuperuser
```

Access at `http://localhost:8000/admin`

### Django Shell

```bash
uv run manage.py shell
```

### Run Tests

```bash
uv run pytest
```

## Redis Setup

**Install:**
- Windows: `choco install redis-64`
- macOS: `brew install redis`
- Linux: `sudo apt install redis-server`

**Start:**
```bash
redis-server
```

**Verify:**
```bash
redis-cli ping  # Should return PONG
```

## CopilotKit Integration

The backend exposes CopilotKit-compatible endpoints:

- `POST /api/copilotkit/info` - Agent information
- `POST /api/copilotkit/agent/{name}` - Execute agent
- `POST /api/copilotkit/agent/{name}/state` - Get state

Frontend uses `@copilotkit/react-core` and `@copilotkit/runtime-client-gql`.

## Troubleshooting

**500 Internal Server Error:**
- Check API keys in `.env`
- Ensure `DEBUG=True` for detailed errors
- Verify Redis is running: `redis-cli ping`

**Authentication Issues:**
- Verify `GOOGLE_CLIENT_ID` matches frontend
- Check Authorization header format
- Ensure Google OAuth is configured correctly

**MCP Connection Failures:**
- Verify Redis connection
- Check server transport configuration
- For stdio: ensure command is executable
- Use `mcpServerHealth` query to diagnose

**Port Conflicts:**
- Backend: port 8000
- Frontend: port 3000
- Redis: port 6379
- Change with `--port` flag if needed

## Learn More

- [Django Documentation](https://docs.djangoproject.com)
- [Strawberry GraphQL](https://strawberry.rocks)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [CopilotKit](https://docs.copilotkit.ai)
- [Model Context Protocol](https://modelcontextprotocol.io)
