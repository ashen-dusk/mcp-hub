# MCP OAuth Implementation Guide

This document describes the OAuth 2.0 implementation for MCP (Model Context Protocol) servers in the MCP Hub application.

---

## Overview

The OAuth implementation allows users to connect to MCP servers that require OAuth 2.0 authorization. It follows industry-standard OAuth flows similar to Claude.ai, with automatic browser redirects and token management.

**Key Features:**
- ✅ Automatic OAuth discovery (RFC 9728, 8414, 7591)
- ✅ Client registration and token storage
- ✅ Browser auto-redirect (no manual copy/paste)
- ✅ Token reuse (reconnect without re-authorization)
- ✅ User-isolated token storage
- ✅ Background token exchange

---

## Architecture

### Backend (Django)
- **OAuth Helper** (`app/mcp/oauth_helper.py`) - OAuth discovery, client registration, token exchange
- **OAuth Storage** (`app/mcp/oauth_storage.py`) - User-isolated file-based token storage
- **OAuth Callback** (`app/views.py:oauth_callback`) - Handles OAuth provider redirects
- **Redis Manager** (`app/mcp/redis_manager.py`) - OAuth session management

### Frontend (Next.js)
- **MCP Page** (`app/mcp/page.tsx`) - Detects OAuth servers and handles callbacks
- **Actions API** (`app/api/mcp/actions/route.ts`) - Routes OAuth initiation to backend
- **GraphQL Mutations** (`lib/graphql.ts`) - `INITIATE_OAUTH_CONNECTION_MUTATION`

---

## Complete OAuth Flow

### First-Time Connection

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. User clicks "Connect" on OAuth MCP server                    │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Frontend checks: requiresOauth2 = true                       │
│    hasExistingConnection = false  →  needsOAuth = true          │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Frontend: POST /api/mcp/actions                              │
│    { action: "initiateOAuth", serverName: "my_server" }         │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Backend: initiateOauthConnection mutation                    │
│    - Generate state: "abc123..."                                │
│    - Store in Redis: state → {server_name, session_id, user_id} │
│    - Perform OAuth discovery:                                   │
│      • GET /.well-known/oauth-protected-resource                │
│      • GET /.well-known/oauth-authorization-server              │
│      • POST /register (client registration)                     │
│      • Save client_info to file storage                         │
│    - Build authorization URL with state                         │
│    - Return { authorizationUrl, state }                         │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Frontend: window.location.href = authorizationUrl            │
│    Browser auto-redirects to OAuth provider                     │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. User authorizes on OAuth provider                            │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. OAuth provider redirects to:                                 │
│    http://localhost:8000/api/oauth-callback?code=...&state=...  │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. Backend /api/oauth-callback:                                 │
│    - Get state from URL                                         │
│    - Lookup Redis: state → {server_name, session_id, user_id}  │
│    - Start background task: complete_oauth_flow()               │
│    - Redirect to: /mcp?server=X&step=success                    │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 9. Background Task (complete_oauth_flow):                       │
│    - Load client_info from file storage                         │
│    - Discover token endpoint                                    │
│    - POST /token (exchange code for access token)               │
│    - Save tokens to file storage                                │
│    - Connect to MCP server (using tokens)                       │
│    - Fetch tools from server                                    │
│    - Update Redis: status=CONNECTED, tools=[...]                │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 10. Browser loads: /mcp?server=X&step=success                   │
│     - Frontend shows toast: "OAuth successful! Connecting..."   │
│     - Refreshes server list after 1 second                      │
│     - Server now shows: connectionStatus = "CONNECTED"          │
└─────────────────────────────────────────────────────────────────┘
```

### Reconnection (Token Reuse)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. User deactivates OAuth server                                │
│    - connectionStatus: CONNECTED → DISCONNECTED                 │
│    - Tokens remain in file storage                              │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. User clicks "Activate" again                                 │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Frontend checks:                                              │
│    requiresOauth2 = true                                         │
│    connectionStatus = "DISCONNECTED"  (has existing connection)  │
│    hasExistingConnection = true  →  needsOAuth = false          │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Frontend: POST /api/mcp/actions                              │
│    { action: "activate", serverName: "my_server" }              │
│    (NOT "initiateOAuth" - uses existing tokens!)                │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Backend: connectMcpServer mutation                           │
│    - Load tokens from file storage                              │
│    - Connect to MCP server (using existing tokens)              │
│    - Fetch tools                                                │
│    - Update Redis: status=CONNECTED, tools=[...]                │
│    - Return immediately (no OAuth flow!)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Implementation Details

### 1. OAuth Discovery

**Location:** `app/mcp/oauth_helper.py:build_authorization_url()`

Uses MCP library's `OAuthClientProvider` to perform RFC-compliant discovery:

```python
# Step 1: Protected Resource Discovery (RFC 9728)
discovery_request = await oauth_provider._discover_protected_resource(response)
discovery_response = await client.send(discovery_request)
await oauth_provider._handle_protected_resource_response(discovery_response)

# Step 2: OAuth Metadata Discovery (RFC 8414)
discovery_urls = [
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration"
]
metadata_response = await client.send(metadata_request)
await oauth_provider._handle_oauth_metadata_response(metadata_response)

# Step 3: Client Registration (RFC 7591)
registration_request = await oauth_provider._register_client()
registration_response = await client.send(registration_request)
await oauth_provider._handle_registration_response(registration_response)
```

### 2. Token Storage

**Location:** `app/mcp/oauth_storage.py:ClientTokenStorage`

User-isolated file-based storage:

```
~/.fastmcp/oauth-mcp-client-cache/
├── user_john_doe/
│   ├── https___mcp.webflow.com_client_info.json
│   └── https___mcp.webflow.com_tokens.json
└── session_anonymous123/
    ├── https___mcp.example.com_client_info.json
    └── https___mcp.example.com_tokens.json
```

**Key Features:**
- Separate storage per user/session
- One file per server (based on base URL)
- Automatic expiry checking
- Token refresh support

### 3. State Management

**Location:** `app/mcp/redis_manager.py:store_oauth_session()`

OAuth state is stored in Redis to link the callback to the original request:

```python
KEY:   mcp:oauth:session:abc123...
VALUE: {
    "state": "abc123...",
    "server_name": "webflow_mcp",
    "session_id": "user_john_doe",
    "user_id": "john_doe",
    "timestamp": "2025-10-26T00:42:43Z"
}
TTL:   600 seconds (10 minutes)
```

### 4. Reconnection Logic

**Location:** `app/mcp/page.tsx:handleServerAction()`

```typescript
const hasExistingConnection =
    server?.connectionStatus === 'CONNECTED' ||
    server?.connectionStatus === 'DISCONNECTED';

const needsOAuth = isOAuthServer && isActivating && !hasExistingConnection;

const actualAction = needsOAuth ? 'initiateOAuth' : 'activate';
```

**Logic:**
- `connectionStatus` is `null` or `undefined` → First time → `initiateOAuth`
- `connectionStatus` is `CONNECTED` or `DISCONNECTED` → Has tokens → `activate`

---

## File Structure

### Backend Files

```
mcp-hub/
├── app/
│   ├── views.py                    # OAuth callback endpoint
│   ├── urls.py                     # /api/oauth-callback route
│   └── mcp/
│       ├── oauth_helper.py         # OAuth discovery & token exchange
│       ├── oauth_storage.py        # User-isolated token storage
│       ├── redis_manager.py        # OAuth session management
│       ├── mcp_schema.py           # initiateOauthConnection mutation
│       └── types.py                # OAuthInitResult type
└── .env
    ├── BACKEND_URL=http://localhost:8000
    └── REDIRECT_URI=http://localhost:8000/api/oauth-callback
```

### Frontend Files

```
mcp-client/
├── app/
│   ├── mcp/page.tsx                # OAuth detection & callback handling
│   └── api/mcp/actions/route.ts    # OAuth action routing
└── lib/
    └── graphql.ts                  # INITIATE_OAUTH_CONNECTION_MUTATION
```

---

## Error Handling

### OAuth Provider Errors

If the OAuth provider returns an error:

```
http://localhost:8000/api/oauth-callback?error=access_denied&error_description=User+denied+access
```

Backend redirects to:
```
http://localhost:3000/mcp?error=access_denied&error_description=User+denied+access
```

Frontend shows toast:
```typescript
toast.error(`OAuth failed: access_denied - User denied access`);
```

### Token Exchange Errors

If token exchange fails, the background task logs the error and sets:
```python
await mcp_redis.set_connection_status(server_name, "FAILED", [], session_id)
```

Frontend polling detects `connectionStatus = "FAILED"` and shows appropriate UI.

---

## Environment Variables

### Backend (.env)

```bash
# Backend URL (used for building OAuth redirect URI)
BACKEND_URL=http://localhost:8000

# OAuth redirect URI - must match what's registered with OAuth provider
REDIRECT_URI=http://localhost:8000/api/oauth-callback

# Frontend URL (for redirecting after OAuth)
NEXT_PUBLIC_APP_URL=http://localhost:3000

# Redis for OAuth session management
REDIS_URL=redis://localhost:6379/0
```

### Frontend (.env.local)

```bash
# Frontend app URL
NEXT_PUBLIC_APP_URL=http://localhost:3000

# Backend API URL
DJANGO_API_URL=http://localhost:8000
BACKEND_URL=http://localhost:8000
```

---

## Production Deployment

### 1. Update Environment Variables

```bash
# Backend
BACKEND_URL=https://api.yourdomain.com
REDIRECT_URI=https://api.yourdomain.com/api/oauth-callback
NEXT_PUBLIC_APP_URL=https://yourdomain.com

# Frontend
NEXT_PUBLIC_APP_URL=https://yourdomain.com
DJANGO_API_URL=https://api.yourdomain.com
```

### 2. Register Redirect URI

Register `https://api.yourdomain.com/api/oauth-callback` with each OAuth provider (Webflow, Google, etc.)

### 3. HTTPS Required

OAuth 2.0 requires HTTPS in production. Ensure your backend has valid SSL certificates.

---

## Testing

### Test OAuth Flow

1. Start backend: `uvicorn assistant.asgi:application --reload`
2. Start frontend: `npm run dev`
3. Navigate to: `http://localhost:3000/mcp`
4. Add an OAuth MCP server with `requiresOauth2=true`
5. Click "Connect"
6. Browser auto-redirects to OAuth provider
7. Authorize
8. Redirected back to `/mcp?server=X&step=success`
9. Server shows `CONNECTED` status with tools

### Test Reconnection

1. Click "Deactivate" on connected OAuth server
2. Status changes to `DISCONNECTED`
3. Click "Activate" again
4. Server connects immediately (no OAuth redirect!)

### Test Error Handling

1. Click "Connect" on OAuth server
2. Deny authorization on OAuth provider
3. Redirected to `/mcp?error=access_denied&error_description=...`
4. Error toast appears

---

## Troubleshooting

### Issue: "OAuth client not registered"

**Cause:** Client info not found in file storage during token exchange

**Solution:**
- Check `~/.fastmcp/oauth-mcp-client-cache/{user_id}/` directory
- Ensure client registration completed during discovery
- Try connecting again (will re-register)

### Issue: OAuth redirect loops

**Cause:** `hasExistingConnection` logic not detecting existing tokens

**Solution:**
- Check `connectionStatus` in server object
- Ensure Redis has correct status after first connection
- Clear file storage and reconnect: `rm -rf ~/.fastmcp/oauth-mcp-client-cache/`

### Issue: "Token exchange failed: 401"

**Cause:** Invalid authorization code or expired state

**Solution:**
- OAuth state expires after 10 minutes
- Complete OAuth flow within time limit
- Increase TTL in `store_oauth_session(ttl=600)`

---

## Security Considerations

1. **State Parameter:** Random 32-byte token prevents CSRF attacks
2. **PKCE:** MCP library automatically uses PKCE (S256) for enhanced security
3. **Token Storage:** File-based with user isolation (not in database)
4. **Redis TTL:** OAuth sessions expire after 10 minutes
5. **HTTPS:** Required in production (enforced by OAuth providers)
6. **Client Secret:** Stored in file system, not exposed to frontend

---

## Comparison: Old vs New Implementation

| Feature | Old (Local Callback Server) | New (API Endpoint) |
|---------|------------------------------|-------------------|
| **Callback mechanism** | Local server on port 8293 | API endpoint `/api/oauth-callback` |
| **Browser opening** | Backend `webbrowser.open()` | Frontend auto-redirect |
| **Flow type** | Synchronous (blocks request) | Async (background task) |
| **Token reuse** | ❌ Re-authorizes every time | ✅ Uses existing tokens |
| **Frontend control** | None | Full control over UX |
| **Production ready** | Requires nginx proxy | Works out of the box |
| **Like Claude.ai** | ❌ | ✅ |

---

## References

- **RFC 9728:** OAuth 2.0 Protected Resource Metadata
- **RFC 8414:** OAuth 2.0 Authorization Server Metadata
- **RFC 7591:** OAuth 2.0 Dynamic Client Registration
- **RFC 6749:** OAuth 2.0 Authorization Framework
- **MCP Spec:** https://spec.modelcontextprotocol.io/

---

## Summary

The OAuth implementation provides a seamless, industry-standard authentication flow for MCP servers:

✅ **Automatic:** Browser redirects happen automatically
✅ **Secure:** State parameters, PKCE, user-isolated storage
✅ **Efficient:** Tokens are reused, no re-authorization needed
✅ **Production-ready:** No local callback server, works with HTTPS
✅ **User-friendly:** Clear error messages, toast notifications

The implementation leverages the official MCP library (`mcp.client.auth`) for all OAuth operations, ensuring compatibility and standards compliance.
