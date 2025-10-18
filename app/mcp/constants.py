"""
Configuration constants for MCP module.

Centralizes all configuration values to improve maintainability
and make it easier to adjust settings without modifying business logic.
"""

# Redis Configuration
REDIS_CONNECTION_TTL = 86400  # 24 hours in seconds
REDIS_KEY_PREFIX = "mcp"

# Connection Timeouts
MCP_CLIENT_TIMEOUT = 30.0  # seconds
TOOL_FETCH_TIMEOUT = 30.0  # seconds

# OAuth Configuration
OAUTH_CLIENT_NAME = "Inspect MCP"
OAUTH_CALLBACK_PORT = 8293
OAUTH_DEFAULT_SCOPES = []

# Connection Status Values
STATUS_CONNECTED = "CONNECTED"
STATUS_DISCONNECTED = "DISCONNECTED"
STATUS_FAILED = "FAILED"

# Operation Result Status
RESULT_OK = "OK"
RESULT_ERROR = "ERROR"
RESULT_TIMEOUT = "TIMEOUT"
RESULT_NOT_FOUND = "NOT_FOUND"
RESULT_DISABLED = "DISABLED"
