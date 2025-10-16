# OAuth User Isolation Fix

## Problem

The application was using FastMCP's `FileTokenStorage` with a shared cache directory (`~/.fastmcp/oauth-mcp-client-cache/`) for all users. This caused OAuth token sharing between different users:

1. User A connects to an MCP server requiring OAuth
2. OAuth tokens are stored in the shared cache directory
3. User B tries to connect to the same server
4. The system reuses User A's tokens instead of initiating a new OAuth flow for User B

## Solution

Implemented **user-isolated token storage** that creates separate cache directories for each user/session:

### Architecture

```
~/.fastmcp/oauth-mcp-client-cache/
├── user_alice/          # User A's tokens
│   └── server_tokens
├── user_bob/            # User B's tokens
│   └── server_tokens
└── user_charlie/        # User C's tokens
    └── server_tokens
```

### Components

#### 1. `ClientTokenStorage` (app/mcp/oauth_storage.py)

Extends `FileTokenStorage` to use user-specific subdirectories:

```python
storage = ClientTokenStorage(
    server_url="https://example.com",
    user_id="alice",        # or username
    session_id="session_123"  # fallback if user_id not available
)
```

#### 2. `ClientOAuth` (app/mcp/oauth_storage.py)

Custom OAuth class that automatically uses user-isolated token storage:

```python
oauth = ClientOAuth(
    mcp_url="https://example.com",
    user_id="alice",
    session_id="session_123",
    client_name="Inspect MCP",
    callback_port=8293,
    scopes=[]
)
```

### Changes Made

1. **app/mcp/oauth_storage.py** (NEW)
   - `ClientTokenStorage`: User-specific token storage
   - `ClientOAuth`: OAuth with automatic user isolation

2. **app/mcp/manager.py**
   - Updated `connect_server()` to use `ClientOAuth`
   - Updated `arestart_mcp_server()` to use `ClientOAuth`
   - Updated `aremove_server()` to clear user-isolated tokens
   - All OAuth operations now use `session_id` for isolation

3. **app/mcp/types.py**
   - Fixed async/sync issue with `owner` field resolver
   - Added `sync_to_async` wrapper for database access in GraphQL context

## Usage

### Connecting to OAuth MCP Server

```python
# Session ID is automatically passed from the GraphQL context
success, message, server = await mcp.connect_server(
    name="finance mcp",
    session_id="himanshu.mehta.sde"
)
```

Each user/session will now get their own OAuth flow and tokens.

### Clearing User Tokens

```python
# Clear all tokens for a specific user
await ClientTokenStorage.clear_user_tokens(
    user_id="alice",
    session_id="session_123"
)
```

### Removing a Server

```python
# Automatically clears user-isolated tokens
await mcp.aremove_server(
    name="finance mcp",
    user=current_user,
    session_id="session_123"
)
```

## Benefits

1. **Security**: Each user has their own OAuth tokens
2. **Privacy**: Users cannot access other users' authenticated connections
3. **Correctness**: Each user goes through their own OAuth flow
4. **Isolation**: Token refresh/revocation affects only the specific user

## Testing

To test the fix:

1. Connect to an OAuth MCP server as User A
2. Verify OAuth flow completes successfully
3. Connect to the same server as User B
4. Verify User B gets their own OAuth flow (not reusing User A's tokens)
5. Both users should have independent connections

## Migration

Existing tokens in the shared cache (`~/.fastmcp/oauth-mcp-client-cache/`) will not be automatically migrated. Users will need to re-authenticate when they first connect after this update.

To clear old shared tokens:

```bash
rm -rf ~/.fastmcp/oauth-mcp-client-cache/
```

The new user-isolated directories will be created automatically on first use.
