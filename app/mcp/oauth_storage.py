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


class ClientOAuth(OAuthClientProvider):
    """
    Production-ready OAuth implementation with user-isolated token storage.

    The redirect URI and callback port can be configured via environment variables:
    - REDIRECT_URI: Public callback URL (default: https://api.quicklit.in/auth-callback)
    - OAUTH_CALLBACK_PORT: Local callback server port (default: 8293)

    In production, configure nginx to forward the public redirect URI to the local
    callback server (e.g., https://api.quicklit.in/auth-callback -> http://localhost:8293/callback).

    This ensures that each user/session has their own OAuth tokens,
    preventing token sharing across different users.
    """

    # Default values (can be overridden by environment variables)
    DEFAULT_REDIRECT_URI = "https://api.quicklit.in/auth-callback"
    DEFAULT_CALLBACK_PORT = 8293

    def __init__(
        self,
        mcp_url: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        client_name: str = "MCP Hub",
        callback_port: Optional[int] = None,
        scopes: Optional[list[str]] = None,
        additional_client_metadata: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize user-isolated OAuth with configurable callback.

        Environment variables:
            REDIRECT_URI: Public callback URL (default: https://api.quicklit.in/auth-callback)
            OAUTH_CALLBACK_PORT: Port for local callback server (default: 8293)

        Args:
            mcp_url: Full URL to the MCP endpoint (e.g. "http://host/mcp/sse/")
            user_id: The user identifier for token isolation
            session_id: The session identifier for token isolation (used if user_id not available)
            client_name: Name for this client during registration
            callback_port: Port for local callback server (overrides OAUTH_CALLBACK_PORT env var)
            scopes: OAuth scopes to request as a list of strings
            additional_client_metadata: Extra fields for OAuthClientMetadata
        """
        # Parse MCP URL
        parsed_url = urlparse(mcp_url)
        server_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # Get redirect URI from environment or use default
        redirect_uri = os.getenv("REDIRECT_URI", self.DEFAULT_REDIRECT_URI)

        # Get callback port from parameter, environment, or use default
        if callback_port is None:
            env_port = os.getenv("OAUTH_CALLBACK_PORT", str(self.DEFAULT_CALLBACK_PORT))
            try:
                callback_port = int(env_port)
            except ValueError:
                logging.warning(f"Invalid OAUTH_CALLBACK_PORT: {env_port}, using default {self.DEFAULT_CALLBACK_PORT}")
                callback_port = self.DEFAULT_CALLBACK_PORT

        self.redirect_port = callback_port

        logging.info(f"Using OAuth redirect URI: {redirect_uri}")
        logging.info(f"Local callback server will run on port: {self.redirect_port}")

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
            **(additional_client_metadata or {}),
        )

        # Create user-isolated token storage
        storage = ClientTokenStorage(
            server_url=server_base_url,
            user_id=user_id,
            session_id=session_id
        )

        # Store metadata for callback handler
        self.server_base_url = server_base_url
        self.user_id = user_id
        self.session_id = session_id

        # Initialize parent class
        super().__init__(
            server_url=server_base_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=self.redirect_handler,
            callback_handler=self.callback_handler,
        )

        logging.info(f"Initialized OAuth for: {user_id or session_id}")

    async def _initialize(self) -> None:
        """Load stored tokens and client info, properly setting token expiry."""
        # Call parent's _initialize to load tokens and client info
        await super()._initialize()

        # If tokens were loaded and have expires_in, update the context's token_expiry_time
        if self.context.current_tokens and self.context.current_tokens.expires_in:
            self.context.update_token_expiry(self.context.current_tokens)

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

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow with automatic retry on stale cached credentials.

        If the OAuth flow fails due to invalid/stale client credentials,
        clears the cache and retries once with fresh registration.
        """
        try:
            # First attempt with potentially cached credentials
            gen = super().async_auth_flow(request)
            response = None
            while True:
                try:
                    yielded_request = await gen.asend(response)
                    response = yield yielded_request
                except StopAsyncIteration:
                    break

        except ClientNotFoundError:
            logging.debug(
                "OAuth client not found on server, clearing cache and retrying..."
            )

            # Clear cached state and retry once
            self._initialized = False

            # Try to clear storage if it supports it
            if hasattr(self.context.storage, "clear"):
                try:
                    self.context.storage.clear()
                except Exception as e:
                    logging.warning(f"Failed to clear OAuth storage cache: {e}")
                    # Can't retry without clearing cache, re-raise original error
                    raise ClientNotFoundError(
                        "OAuth client not found and cache could not be cleared"
                    ) from e
            else:
                logging.warning(
                    "Storage does not support clear() - cannot retry with fresh credentials"
                )
                # Can't retry without clearing cache, re-raise original error
                raise

            gen = super().async_auth_flow(request)
            response = None
            while True:
                try:
                    yielded_request = await gen.asend(response)
                    response = yield yielded_request
                except StopAsyncIteration:
                    break

    @staticmethod
    def _get_user_cache_dir(user_id: Optional[str] = None, session_id: Optional[str] = None) -> Path:
        """Get the user-specific cache directory."""
        identifier = user_id or session_id or "anonymous"
        base_cache_dir = default_cache_dir()
        user_cache_dir = base_cache_dir / f"user_{identifier}"
        user_cache_dir.mkdir(parents=True, exist_ok=True)
        return user_cache_dir
