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

        logging.info(f"[OAuth] Initializing OAuth client for user={user_id or session_id}")
        logging.info(f"[OAuth] MCP server URL: {server_base_url}")
        logging.info(f"[OAuth] Redirect URI: {redirect_uri}")
        logging.info(f"[OAuth] Callback port: {self.redirect_port}")

        # Prepare scopes
        scopes_str: str
        if isinstance(scopes, list):
            scopes_str = " ".join(scopes)
        elif scopes is not None:
            scopes_str = str(scopes)
        else:
            scopes_str = ""

        if scopes_str:
            logging.info(f"[OAuth] Requested scopes: {scopes_str}")

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

        logging.info(f"[OAuth] Successfully initialized OAuth for user={user_id or session_id}")

    async def _initialize(self) -> None:
        """Load stored tokens and client info, properly setting token expiry."""
        logging.debug(f"[OAuth] Loading stored tokens for user={self.user_id or self.session_id}")

        # Call parent's _initialize to load tokens and client info
        await super()._initialize()

        # If tokens were loaded and have expires_in, update the context's token_expiry_time
        if self.context.current_tokens and self.context.current_tokens.expires_in:
            self.context.update_token_expiry(self.context.current_tokens)
            logging.info(f"[OAuth] Loaded cached tokens (expires in {self.context.current_tokens.expires_in}s)")
        elif self.context.current_tokens:
            logging.info(f"[OAuth] Loaded cached tokens (no expiry)")
        else:
            logging.debug(f"[OAuth] No cached tokens found, will perform fresh OAuth flow")

    async def redirect_handler(self, authorization_url: str) -> None:
        """
        Open browser for authorization.

        This is kept from the base OAuth implementation to automatically
        open the authorization URL in the user's browser.
        """
        logging.info(f"[OAuth] Starting authorization flow for user={self.user_id or self.session_id}")
        logging.debug(f"[OAuth] Authorization URL: {authorization_url}")

        # Pre-flight check to detect invalid client_id before opening browser
        logging.debug(f"[OAuth] Performing pre-flight check to authorization endpoint")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(authorization_url, follow_redirects=False, timeout=10.0)
                logging.debug(f"[OAuth] Pre-flight response status: {response.status_code}")

                # Check for client not found error (400 typically means bad client_id)
                if response.status_code == 400:
                    logging.error(f"[OAuth] OAuth client not found (400) - cached credentials may be stale")
                    raise ClientNotFoundError(
                        "OAuth client not found - cached credentials may be stale"
                    )

                # OAuth typically returns redirects, but some providers return 200 with HTML login pages
                if response.status_code not in (200, 302, 303, 307, 308):
                    logging.error(f"[OAuth] Unexpected authorization response: {response.status_code}")
                    raise RuntimeError(
                        f"Unexpected authorization response: {response.status_code}"
                    )

                logging.info(f"[OAuth] Pre-flight check passed (status {response.status_code})")
            except httpx.RequestError as e:
                logging.error(f"[OAuth] Pre-flight check failed: {e}")
                raise

        logging.info(f"[OAuth] Opening authorization URL in browser")
        webbrowser.open(authorization_url)
        logging.info(f"[OAuth] Waiting for user to complete authorization in browser...")

    async def callback_handler(self) -> tuple[str, str | None]:
        """
        Handle OAuth callback by running local server.

        Creates a local callback server that listens on the configured port.
        In production, nginx forwards the public callback URL to this local server.
        """
        logging.info(f"[OAuth] Setting up callback server for user={self.user_id or self.session_id}")

        # Create a future to capture the OAuth response
        response_future = asyncio.get_running_loop().create_future()

        # Create local callback server
        logging.debug(f"[OAuth] Creating callback server on port {self.redirect_port}")
        server: Server = create_oauth_callback_server(
            port=self.redirect_port,
            server_url=self.server_base_url,
            response_future=response_future,
        )

        # Run server until response is received with timeout logic
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.serve)
            logging.info(
                f"[OAuth] 🎧 Callback server listening on http://localhost:{self.redirect_port}/callback"
            )
            logging.info(f"[OAuth] Waiting for OAuth provider to redirect back...")

            TIMEOUT = 300.0  # 5 minute timeout
            try:
                with anyio.fail_after(TIMEOUT):
                    logging.debug(f"[OAuth] Waiting for callback (timeout: {TIMEOUT}s)")
                    auth_code, state = await response_future
                    logging.info(f"[OAuth] ✅ Received authorization code (length: {len(auth_code) if auth_code else 0})")
                    logging.debug(f"[OAuth] State parameter: {state}")
                    return auth_code, state
            except TimeoutError:
                logging.error(f"[OAuth] ❌ Callback timed out after {TIMEOUT} seconds")
                raise TimeoutError(f"OAuth callback timed out after {TIMEOUT} seconds")
            finally:
                logging.debug(f"[OAuth] Shutting down callback server")
                server.should_exit = True
                await asyncio.sleep(0.1)  # Allow server to shut down gracefully
                tg.cancel_scope.cancel()
                logging.debug(f"[OAuth] Callback server stopped")

        logging.error(f"[OAuth] ❌ OAuth callback handler could not be started")
        raise RuntimeError("OAuth callback handler could not be started")

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow with automatic retry on stale cached credentials.

        If the OAuth flow fails due to invalid/stale client credentials,
        clears the cache and retries once with fresh registration.
        """
        logging.debug(f"[OAuth] Starting auth flow for user={self.user_id or self.session_id}")
        logging.debug(f"[OAuth] Request URL: {request.url}")

        try:
            # First attempt with potentially cached credentials
            logging.debug(f"[OAuth] Attempting auth flow (first attempt)")
            gen = super().async_auth_flow(request)
            response = None
            while True:
                try:
                    yielded_request = await gen.asend(response)
                    response = yield yielded_request
                except StopAsyncIteration:
                    logging.info(f"[OAuth] ✅ Auth flow completed successfully")
                    break

        except ClientNotFoundError as e:
            logging.warning(
                f"[OAuth] OAuth client not found on server, clearing cache and retrying..."
            )
            logging.debug(f"[OAuth] ClientNotFoundError details: {e}")

            # Clear cached state and retry once
            self._initialized = False

            # Try to clear storage if it supports it
            if hasattr(self.context.storage, "clear"):
                try:
                    logging.info(f"[OAuth] Clearing OAuth storage cache for retry")
                    self.context.storage.clear()
                    logging.info(f"[OAuth] Cache cleared successfully")
                except Exception as clear_error:
                    logging.error(f"[OAuth] Failed to clear OAuth storage cache: {clear_error}")
                    # Can't retry without clearing cache, re-raise original error
                    raise ClientNotFoundError(
                        "OAuth client not found and cache could not be cleared"
                    ) from clear_error
            else:
                logging.error(
                    f"[OAuth] Storage does not support clear() - cannot retry with fresh credentials"
                )
                # Can't retry without clearing cache, re-raise original error
                raise

            logging.info(f"[OAuth] Retrying auth flow with fresh credentials (second attempt)")
            gen = super().async_auth_flow(request)
            response = None
            while True:
                try:
                    yielded_request = await gen.asend(response)
                    response = yield yielded_request
                except StopAsyncIteration:
                    logging.info(f"[OAuth] ✅ Auth flow completed successfully on retry")
                    break

    @staticmethod
    def _get_user_cache_dir(user_id: Optional[str] = None, session_id: Optional[str] = None) -> Path:
        """Get the user-specific cache directory."""
        identifier = user_id or session_id or "anonymous"
        base_cache_dir = default_cache_dir()
        user_cache_dir = base_cache_dir / f"user_{identifier}"
        user_cache_dir.mkdir(parents=True, exist_ok=True)
        return user_cache_dir
