"""
User-isolated OAuth token storage for MCP servers.

This module provides a custom token storage implementation that isolates
OAuth tokens per user/session to prevent token sharing across different users.
"""

import logging
from pathlib import Path
from typing import Optional
from fastmcp.client.auth.oauth import FileTokenStorage, default_cache_dir
from fastmcp.client.auth import OAuth as BaseOAuth


class ClientTokenStorage(FileTokenStorage):
    """
    Token storage that isolates OAuth tokens per user.

    Extends FileTokenStorage to use user-specific subdirectories within
    the cache directory, preventing token sharing between users.
    """

    def __init__(self, server_url: str, user_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        Initialize user-isolated token storage.

        Args:
            server_url: The MCP server URL
            user_id: The user identifier (username or user ID)
            session_id: The session identifier (used if user_id not available)
        """
        self.user_id = user_id
        self.session_id = session_id

        # Create user-specific cache directory
        base_cache_dir = default_cache_dir()

        # Use user_id or session_id to create isolated storage
        identifier = user_id or session_id or "anonymous"
        user_cache_dir = base_cache_dir / f"user_{identifier}"

        # Ensure the directory exists
        user_cache_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"Using user-isolated token storage at: {user_cache_dir}")

        # Initialize parent class with user-specific cache directory
        super().__init__(server_url=server_url, cache_dir=user_cache_dir)

    @classmethod
    async def clear_user_tokens(cls, user_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        Clear all tokens for a specific user.

        Args:
            user_id: The user identifier
            session_id: The session identifier
        """
        identifier = user_id or session_id or "anonymous"
        base_cache_dir = default_cache_dir()
        user_cache_dir = base_cache_dir / f"user_{identifier}"

        if user_cache_dir.exists():
            import shutil
            shutil.rmtree(user_cache_dir)
            logging.info(f"Cleared all tokens for user: {identifier}")


class ClientOAuth(BaseOAuth):
    """
    OAuth implementation that uses user-isolated token storage.

    This ensures that each user/session has their own OAuth tokens,
    preventing token sharing across different users.
    """

    def __init__(
        self,
        mcp_url: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        client_name: str = "Inspect MCP",
        callback_port: int = 8293,
        scopes: Optional[list] = None,
    ):
        """
        Initialize user-isolated OAuth.

        Args:
            mcp_url: The MCP server URL
            user_id: The user identifier
            session_id: The session identifier
            client_name: OAuth client name
            callback_port: Port for OAuth callback
            scopes: OAuth scopes to request
        """
        # Create user-isolated token storage directory
        user_cache_dir = self._get_user_cache_dir(user_id, session_id)

        # Initialize parent OAuth with user-specific cache directory
        super().__init__(
            mcp_url=mcp_url,
            client_name=client_name,
            callback_port=callback_port,
            scopes=scopes or [],
            token_storage_cache_dir=user_cache_dir
        )

        self.user_id = user_id
        self.session_id = session_id

        logging.info(f"Initialized user-isolated OAuth for: {user_id or session_id} with cache dir: {user_cache_dir}")

    @staticmethod
    def _get_user_cache_dir(user_id: Optional[str] = None, session_id: Optional[str] = None) -> Path:
        """Get the user-specific cache directory."""
        identifier = user_id or session_id or "anonymous"
        base_cache_dir = default_cache_dir()
        user_cache_dir = base_cache_dir / f"user_{identifier}"
        user_cache_dir.mkdir(parents=True, exist_ok=True)
        return user_cache_dir
