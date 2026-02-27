# 🚀 MCP Hub

mcp-hub is a backend service for registering and managing Model Context Protocol (MCP) servers, with built-in LangGraph agent support for dynamic interactions.

---

## ✨ Key Features

- 🔧 **MCP Server Management** - Full CRUD operations for standard and custom MCP servers.
- 📂 **Categorization** - Organized server ecosystem with custom icons and colors.
- 🤖 **Agents** - LangGraph-powered agents with dynamic tool binding.
- 🔐 **Authentication** - Google OAuth integration with NextAuth.js compatibility.
- 📊 **GraphQL API** - Flexible Strawberry-powered API for seamless frontend integration.

---

## 🛠️ Tech Stack

- **Core:** Django 5.2 | Python 3.12+
- **API:** GraphQL (Strawberry Django)
- **Agent:** LangGraph | OpenAI / DeepSeek
- **Connectivity:** Redis | CopilotKit
- **Database:** SQLite (PostgreSQL compatible)

---

## 🚦 Quick Start

### 1. Installation

We recommend using **uv** for the fastest setup:

```bash
# Setup environment and install dependencies
uv venv
uv pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory:

```env
SECRET_KEY=your_secret_key
DEBUG=True
GOOGLE_CLIENT_ID=your_id.apps.googleusercontent.com
OPENAI_API_KEY=sk-...
REDIS_URL=redis://localhost:6379/0
```

### 3. Initialize & Run

```bash
# Apply migrations
uv run manage.py migrate

# Seed default categories (optional)
uv run python seed_categories.py

# Launch the engine
uv run uvicorn assistant.asgi:application --reload
```

> [!TIP]
> The backend runs at `http://localhost:8000`. You can explore the API via the GraphiQL interactive playground at `/graphql`.

---

## 📂 Project Anatomy

- `app/mcp/` - Core logic for server configs, transport adapters, and state.
- `app/agent/` - LangGraph definition, chat nodes, and LLM configuration.
- `app/auth/` - Authentication middleware and schema.
- `assistant/` - Global project settings and ASGI configuration.

---

## 🔌 Integration

The backend is purpose-built to work with **CopilotKit**, exposing specialized endpoints for agent interaction:

- `POST /api/copilotkit/info`
- `POST /api/copilotkit/agent/{name}`

---

## 🧪 Development

- **Admin:** Create a superuser (`uv run manage.py createsuperuser`) and visit `/admin`.
- **Testing:** Run the suite with `uv run pytest`.
- **Redis:** Ensure `redis-server` is active for connection state persistence.

---

## 📚 Learn More

- [Model Context Protocol](https://modelcontextprotocol.io)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Strawberry GraphQL](https://strawberry.rocks)
- [CopilotKit Docs](https://docs.copilotkit.ai)
