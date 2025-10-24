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
from urllib.parse import urlparse
from pydantic import AnyHttpUrl
from mcp.shared.auth import OAuthClientMetadata

from fastmcp.client.auth.oauth import FileTokenStorage, default_cache_dir
from fastmcp.client.auth import OAuth as BaseOAuth
from fastmcp.utilities.http import find_available_port
from mcp.client.auth import OAuthClientProvider
import webbrowser
import httpx
from fastmcp.client.auth.oauth import ClientNotFoundError

import asyncio
import anyio
from fastmcp.client.oauth_callback import create_oauth_callback_server
from uvicorn.server import Server

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
    Production-ready OAuth implementation with user-isolated token storage.

    Supports configurable public callback URLs for nginx reverse proxy setups.
    In production, the OAuth provider redirects to a public URL (e.g.,
    https://api.quicklit.in/gen-api/auth_callback), and nginx forwards
    this to the local callback server.

    Environment variables:
        OAUTH_CALLBACK_URL: Public callback URL (optional, defaults to localhost)
        OAUTH_CALLBACK_PORT: Port for local callback server (optional, default: 8293)

    This ensures that each user/session has their own OAuth tokens,
    preventing token sharing across different users.
    """

    def __init__(
        self,
        mcp_url: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        client_name: str = "MCP Hub",
        callback_port: Optional[int] = None,
        scopes: Optional[list] = None,
    ):
        """
        Initialize user-isolated OAuth with production callback support.

        Args:
            mcp_url: The MCP server URL
            user_id: The user identifier
            session_id: The session identifier
            client_name: OAuth client name
            callback_port: Port for OAuth callback (overrides OAUTH_CALLBACK_PORT env)
            scopes: OAuth scopes to request
        """
        # Get configuration from environment
        public_callback_url = os.getenv("OAUTH_CALLBACK_URL")
        env_callback_port = os.getenv("OAUTH_CALLBACK_PORT", "8293")

        # Determine callback port
        if callback_port is None:
            try:
                callback_port = int(env_callback_port)
            except ValueError:
                callback_port = 8293

        # Create user-isolated token storage directory
        user_cache_dir = self._get_user_cache_dir(user_id, session_id)

        # Parse MCP URL
        parsed_url = urlparse(mcp_url)
        server_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # Determine redirect URI
        if public_callback_url:
            # Production: Use public URL with nginx forwarding
            redirect_uri = public_callback_url
            logging.info(f"Using public OAuth callback URL: {redirect_uri}")
            logging.info(f"Local callback server will run on port: {callback_port}")
            logging.info("Ensure nginx is configured to forward public URL to localhost:{callback_port}/callback")
        else:
            # Development: Use localhost
            redirect_uri = f"http://localhost:{callback_port}/callback"
            logging.info(f"Using localhost OAuth callback URL: {redirect_uri}")

        # Set up port for local callback server
        self.redirect_port = callback_port

        # Prepare scopes
        scopes_str: str
        if isinstance(scopes, list):
            scopes_str = " ".join(scopes)
        elif scopes is not None:
            scopes_str = str(scopes)
        else:
            scopes_str = ""

        # Build client metadata with custom redirect URI
        client_metadata = OAuthClientMetadata(
            client_name=client_name,
            redirect_uris=[AnyHttpUrl(redirect_uri)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=scopes_str,
        )

        # Create server-specific token storage
        storage = FileTokenStorage(
            server_url=server_base_url,
            cache_dir=user_cache_dir
        )

        # Store metadata for callback handler
        self.server_base_url = server_base_url
        self.user_id = user_id
        self.session_id = session_id

        # Initialize parent class with custom redirect_handler and callback_handler
        # We need to call the grandparent's __init__ to avoid the default redirect_uri
        OAuthClientProvider.__init__(
            self,
            server_url=server_base_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=self.redirect_handler,
            callback_handler=self.callback_handler,
        )

        logging.info(f"Initialized OAuth for: {user_id or session_id} with cache dir: {user_cache_dir}")

    async def redirect_handler(self, authorization_url: str) -> None:
        """
        Open browser for authorization.

        This is kept from the base OAuth implementation to automatically
        open the authorization URL in the user's browser.
        """

        # Pre-flight check to detect invalid client_id before opening browser
        async with httpx.AsyncClient() as client:
            response = await client.get(authorization_url, follow_redirects=False)

            # Check for client not found error (400 typically means bad client_id)
            if response.status_code == 400:
                raise ClientNotFoundError(
                    "OAuth client not found - cached credentials may be stale"
                )

            # OAuth typically returns redirects, but some providers return 200 with HTML login pages
            if response.status_code not in (200, 302, 303, 307, 308):
                raise RuntimeError(
                    f"Unexpected authorization response: {response.status_code}"
                )

        logging.info(f"Opening OAuth authorization URL in browser: {authorization_url}")
        webbrowser.open(authorization_url)

    async def callback_handler(self) -> tuple[str, str | None]:
        """
        Handle OAuth callback by running local server.

        Creates a local callback server that listens on the configured port.
        In production, nginx forwards the public callback URL to this local server.
        """

        # Create a future to capture the OAuth response
        response_future = asyncio.get_running_loop().create_future()

        # Create local callback server
        server: Server = create_oauth_callback_server(
            port=self.redirect_port,
            server_url=self.server_base_url,
            response_future=response_future,
        )

        # Run server until response is received with timeout logic
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.serve)
            logging.info(
                f"🎧 OAuth callback server listening on http://localhost:{self.redirect_port}/callback"
            )

            TIMEOUT = 300.0  # 5 minute timeout
            try:
                with anyio.fail_after(TIMEOUT):
                    auth_code, state = await response_future
                    return auth_code, state
            except TimeoutError:
                raise TimeoutError(f"OAuth callback timed out after {TIMEOUT} seconds")
            finally:
                server.should_exit = True
                await asyncio.sleep(0.1)  # Allow server to shut down gracefully
                tg.cancel_scope.cancel()

        raise RuntimeError("OAuth callback handler could not be started")

    @staticmethod
    def _get_user_cache_dir(user_id: Optional[str] = None, session_id: Optional[str] = None) -> Path:
        """Get the user-specific cache directory."""
        identifier = user_id or session_id or "anonymous"
        base_cache_dir = default_cache_dir()
        user_cache_dir = base_cache_dir / f"user_{identifier}"
        user_cache_dir.mkdir(parents=True, exist_ok=True)
        return user_cache_dir
