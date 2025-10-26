"""
User-isolated OAuth token storage for MCP servers.

This module provides a custom token storage implementation that isolates
OAuth tokens per user/session to prevent token sharing across different users.

It also provides production-ready OAuth with configurable public callback URLs
that work with nginx reverse proxy setups.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Any
from collections.abc import AsyncGenerator
from urllib.parse import urlparse
from pydantic import AnyHttpUrl
from mcp.shared.auth import OAuthClientMetadata

from fastmcp.client.auth.oauth import FileTokenStorage, default_cache_dir, ClientNotFoundError
from fastmcp.client.oauth_callback import create_oauth_callback_server
from mcp.client.auth import OAuthClientProvider
from uvicorn.server import Server

import asyncio
import anyio
import webbrowser
import httpx
from collections.abc import AsyncGenerator
from mcp.shared.auth import OAuthToken


class SimpleTokenAuth(httpx.Auth):
    """
    Simple token-based auth that uses existing OAuth tokens without callback handlers.

    This is used for reconnecting to servers where tokens already exist,
    avoiding the need to set up local callback servers or trigger OAuth flows.
    """

    def __init__(self, server_url: str, user_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        Initialize simple token auth.

        Args:
            server_url: The MCP server URL
            user_id: The user identifier
            session_id: The session identifier
        """
        self.storage = ClientTokenStorage(
            server_url=server_url,
            user_id=user_id,
            session_id=session_id
        )
        self._tokens: Optional[OAuthToken] = None

    async def _ensure_tokens(self) -> Optional[OAuthToken]:
        """Load tokens from storage if not already loaded."""
        if self._tokens is None:
            # Load tokens from storage using the storage's get_tokens method
            try:
                self._tokens = await self.storage.get_tokens()
                if self._tokens:
                    logging.debug(f"[SimpleTokenAuth] Loaded existing tokens from storage")
                else:
                    logging.warning(f"[SimpleTokenAuth] No tokens found in storage")
            except Exception as e:
                logging.error(f"[SimpleTokenAuth] Failed to load tokens: {e}")
        return self._tokens

    def auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Synchronous auth flow (not supported, use async_auth_flow instead)."""
        raise NotImplementedError("Use async_auth_flow instead")

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """
        Add OAuth token to request headers.

        Args:
            request: The HTTP request to authenticate

        Yields:
            Authenticated request
        """
        tokens = await self._ensure_tokens()

        if not tokens or not tokens.access_token:
            logging.error(f"[SimpleTokenAuth] No access token available")
            raise RuntimeError("No OAuth tokens available. Please reconnect to the server.")

        # Add Authorization header
        request.headers["Authorization"] = f"Bearer {tokens.access_token}"

        # Yield the authenticated request
        response = yield request

        # If we get 401, tokens might be expired (but we don't auto-refresh in simple mode)
        if response.status_code == 401:
            logging.warning(f"[SimpleTokenAuth] Got 401 Unauthorized - tokens may be expired")
            # Don't retry, just let it fail so user knows to re-authorize


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

        logging.info(f"[OAuth Storage] Using user-isolated token storage at: {user_cache_dir}")
        logging.debug(f"[OAuth Storage] Server URL: {server_url}, User: {identifier}")

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

        logging.info(f"[OAuth Storage] Attempting to clear tokens for user: {identifier}")

        if user_cache_dir.exists():
            import shutil
            try:
                shutil.rmtree(user_cache_dir)
                logging.info(f"[OAuth Storage] ✅ Cleared all tokens for user: {identifier}")
            except Exception as e:
                logging.error(f"[OAuth Storage] ❌ Failed to clear tokens for user {identifier}: {e}")
                raise
        else:
            logging.debug(f"[OAuth Storage] No token cache found for user: {identifier}")
