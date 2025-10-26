"""
Manual OAuth helper for MCP servers.

Properly handles OAuth discovery and token exchange using MCP library primitives.
"""

import logging
import secrets
import os
from typing import Tuple, Optional
from urllib.parse import urlencode, urlparse, urljoin

import httpx
from pydantic import AnyHttpUrl

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientMetadata,
    OAuthClientInformationFull,
    OAuthToken,
    OAuthMetadata,
)

from .models import MCPServer
from .redis_manager import mcp_redis
from .oauth_storage import ClientTokenStorage


async def initiate_oauth_flow(
    server: MCPServer,
    session_id: str,
    user_id: Optional[str] = None
) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """
    Initiate OAuth flow for an MCP server.

    Performs OAuth discovery, client registration, and builds authorization URL.

    Args:
        server: MCPServer instance
        session_id: Session identifier
        user_id: Optional user identifier

    Returns:
        Tuple of (success, message, authorization_url, state)
    """
    try:
        logging.info(f"[OAuth Helper] Initiating OAuth for server: {server.name}")

        # Generate secure random state
        state = secrets.token_urlsafe(32)

        # Store OAuth session in Redis
        await mcp_redis.store_oauth_session(
            state=state,
            server_name=server.name,
            session_id=session_id,
            user_id=user_id,
            ttl=600  # 10 minutes to complete OAuth
        )

        # Perform OAuth discovery and build authorization URL
        authorization_url = await build_authorization_url(server, state, session_id, user_id)

        if not authorization_url:
            return False, "Failed to build OAuth authorization URL", None, None

        logging.info(f"[OAuth Helper] ✅ Generated auth URL for {server.name}")
        return True, "OAuth flow initiated", authorization_url, state

    except Exception as e:
        logging.exception(f"[OAuth Helper] Error initiating OAuth: {e}")
        return False, f"Failed to initiate OAuth: {str(e)}", None, None


async def build_authorization_url(
    server: MCPServer,
    state: str,
    session_id: str,
    user_id: Optional[str] = None
) -> Optional[str]:
    """
    Build OAuth authorization URL using MCP discovery protocol.

    This performs:
    1. Protected resource discovery (RFC 9728)
    2. OAuth metadata discovery (RFC 8414)
    3. Client registration (RFC 7591)
    4. Authorization URL construction

    Args:
        server: MCPServer instance
        state: OAuth state parameter
        session_id: Session identifier
        user_id: Optional user identifier

    Returns:
        Authorization URL string, or None if failed
    """
    try:
        backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
        redirect_uri = f"{backend_url}/api/oauth-callback"

        logging.info(f"[OAuth Helper] Starting OAuth discovery for {server.name}")

        # Create client metadata
        client_metadata = OAuthClientMetadata(
            client_name="MCP Hub",
            redirect_uris=[AnyHttpUrl(redirect_uri)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="",
        )

        # Create user-isolated storage
        storage = ClientTokenStorage(
            server_url=server.url,
            user_id=user_id,
            session_id=session_id
        )

        # Dummy handlers (we won't actually use them)
        async def dummy_redirect_handler(url: str) -> None:
            pass

        async def dummy_callback_handler() -> Tuple[str, Optional[str]]:
            return "", None

        # Create OAuth provider
        oauth_provider = OAuthClientProvider(
            server_url=server.url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=dummy_redirect_handler,
            callback_handler=dummy_callback_handler,
            timeout=300.0
        )

        # Manually perform the discovery and registration steps
        # This mimics what happens in the auth_flow, but stops before authorization

        # Step 1: Try to load existing client info and metadata
        await oauth_provider._initialize()

        if oauth_provider.context.client_info and oauth_provider.context.oauth_metadata:
            logging.info(f"[OAuth Helper] Using cached client info")
        else:
            logging.info(f"[OAuth Helper] Performing OAuth discovery and registration")

            # Make an unauthenticated request to trigger discovery
            async with httpx.AsyncClient() as client:
                # This will get a 401 response
                response = await client.get(
                    server.url,
                    headers={"Accept": "application/json"},
                    follow_redirects=False,
                    timeout=10.0
                )

                logging.info(f"[OAuth Helper] Initial request returned status: {response.status_code}")

                if response.status_code == 401:
                    # Step 2: Discover protected resource metadata
                    discovery_request = await oauth_provider._discover_protected_resource(response)
                    discovery_response = await client.send(discovery_request)
                    await oauth_provider._handle_protected_resource_response(discovery_response)

                    # Step 3: Discover OAuth metadata
                    discovery_urls = oauth_provider._get_discovery_urls()
                    for url in discovery_urls:
                        metadata_request = oauth_provider._create_oauth_metadata_request(url)
                        metadata_response = await client.send(metadata_request)

                        if metadata_response.status_code == 200:
                            try:
                                await oauth_provider._handle_oauth_metadata_response(metadata_response)
                                logging.info(f"[OAuth Helper] ✅ Discovered OAuth metadata from {url}")
                                break
                            except Exception:
                                continue

                    # Step 4: Register client if needed
                    if not oauth_provider.context.client_info:
                        registration_request = await oauth_provider._register_client()
                        if registration_request:
                            registration_response = await client.send(registration_request)
                            await oauth_provider._handle_registration_response(registration_response)
                            logging.info(f"[OAuth Helper] ✅ Registered OAuth client")
                else:
                    # Server didn't return 401 - try alternative OAuth discovery
                    logging.warning(f"[OAuth Helper] Server returned {response.status_code} instead of 401. Attempting alternative OAuth discovery...")

                    # Try standard OAuth discovery URLs directly
                    parsed = urlparse(server.url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}"

                    discovery_urls = [
                        urljoin(base_url, "/.well-known/oauth-authorization-server"),
                        urljoin(base_url, "/.well-known/openid-configuration"),
                    ]

                    metadata_discovered = False
                    for discovery_url in discovery_urls:
                        try:
                            logging.info(f"[OAuth Helper] Trying discovery URL: {discovery_url}")
                            metadata_response = await client.get(discovery_url, timeout=10.0)

                            if metadata_response.status_code == 200:
                                metadata_request = oauth_provider._create_oauth_metadata_request(discovery_url)
                                await oauth_provider._handle_oauth_metadata_response(metadata_response)
                                metadata_discovered = True
                                logging.info(f"[OAuth Helper] ✅ Discovered OAuth metadata from {discovery_url}")
                                break
                        except Exception as e:
                            logging.debug(f"[OAuth Helper] Discovery failed for {discovery_url}: {e}")
                            continue

                    if not metadata_discovered:
                        logging.error(f"[OAuth Helper] Failed to discover OAuth metadata from standard URLs")
                        return None

                    # Register client if needed
                    if not oauth_provider.context.client_info:
                        registration_request = await oauth_provider._register_client()
                        if registration_request:
                            registration_response = await client.send(registration_request)
                            await oauth_provider._handle_registration_response(registration_response)
                            logging.info(f"[OAuth Helper] ✅ Registered OAuth client")

        # Now build the authorization URL manually
        if not oauth_provider.context.client_info:
            logging.error(f"[OAuth Helper] No client info available for {server.name}")
            logging.error(f"[OAuth Helper] This may mean:")
            logging.error(f"  1. The server doesn't properly implement OAuth discovery (RFC 9728)")
            logging.error(f"  2. The server URL is incorrect or unreachable")
            logging.error(f"  3. The server doesn't support dynamic client registration")
            logging.error(f"[OAuth Helper] Server URL: {server.url}")
            return None

        if not oauth_provider.context.oauth_metadata:
            logging.error(f"[OAuth Helper] No OAuth metadata available for {server.name}")
            logging.error(f"[OAuth Helper] The server may not have OAuth metadata at standard discovery endpoints")
            logging.error(f"[OAuth Helper] Server URL: {server.url}")
            return None

        # Get authorization endpoint
        if oauth_provider.context.oauth_metadata.authorization_endpoint:
            auth_endpoint = str(oauth_provider.context.oauth_metadata.authorization_endpoint)
        else:
            auth_base_url = oauth_provider.context.get_authorization_base_url(server.url)
            auth_endpoint = urljoin(auth_base_url, "/authorize")

        # Build authorization parameters
        auth_params = {
            "response_type": "code",
            "client_id": oauth_provider.context.client_info.client_id,
            "redirect_uri": redirect_uri,
            "state": state,  # Use our custom state
            "scope": client_metadata.scope or "",
        }

        # Build URL
        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"

        logging.info(f"[OAuth Helper] ✅ Built authorization URL")
        logging.debug(f"[OAuth Helper] URL: {authorization_url[:100]}...")

        return authorization_url

    except Exception as e:
        logging.exception(f"[OAuth Helper] ❌ Error building authorization URL: {e}")
        return None


async def exchange_authorization_code(
    server: MCPServer,
    code: str,
    session_id: str,
    user_id: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Exchange authorization code for access tokens.

    Uses the stored client info from the discovery phase.

    Args:
        server: MCPServer instance
        code: Authorization code
        session_id: Session identifier
        user_id: Optional user identifier

    Returns:
        Tuple of (success, message)
    """
    try:
        logging.info(f"[OAuth Helper] Exchanging authorization code for {server.name}")

        # Create storage to load client info
        storage = ClientTokenStorage(
            server_url=server.url,
            user_id=user_id,
            session_id=session_id
        )

        # Load client info that was saved during discovery
        # IMPORTANT: We need to get it directly from storage, not through get_client_info()
        # because get_client_info() checks for tokens and deletes client info if not found
        client_info_key = storage._get_storage_key("client_info")
        client_info_data = await storage._storage.get(client_info_key)

        if not client_info_data:
            logging.error("[OAuth Helper] No client info in storage - OAuth not initialized")
            return False, "OAuth client not registered. Please try connecting again."

        client_info = OAuthClientInformationFull.model_validate(client_info_data)

        # Load OAuth metadata to get token endpoint
        # We need to discover it again since we don't cache it
        async with httpx.AsyncClient() as client:
            # Try to discover OAuth metadata
            parsed = urlparse(server.url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Try standard discovery URLs
            discovery_urls = [
                urljoin(base_url, "/.well-known/oauth-authorization-server"),
                urljoin(base_url, "/.well-known/openid-configuration"),
            ]

            token_endpoint = None
            for discovery_url in discovery_urls:
                try:
                    resp = await client.get(discovery_url, timeout=10.0)
                    if resp.status_code == 200:
                        metadata = OAuthMetadata.model_validate_json(await resp.aread())
                        if metadata.token_endpoint:
                            token_endpoint = str(metadata.token_endpoint)
                            logging.info(f"[OAuth Helper] Found token endpoint: {token_endpoint}")
                            break
                except Exception as e:
                    logging.debug(f"[OAuth Helper] Discovery failed for {discovery_url}: {e}")
                    continue

            if not token_endpoint:
                # Fallback to /token
                token_endpoint = urljoin(base_url, "/token")
                logging.warning(f"[OAuth Helper] Using fallback token endpoint: {token_endpoint}")

            # Exchange code for tokens
            backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
            redirect_uri = f"{backend_url}/api/oauth-callback"

            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_info.client_id,
            }

            if client_info.client_secret:
                token_data["client_secret"] = client_info.client_secret

            logging.debug(f"[OAuth Helper] Exchanging code at: {token_endpoint}")

            response = await client.post(
                token_endpoint,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0
            )

            if response.status_code != 200:
                error_text = await response.aread()
                logging.error(f"[OAuth Helper] Token exchange failed: {response.status_code} - {error_text}")
                return False, f"Token exchange failed: {response.status_code}"

            # Parse and store tokens
            token_json = response.json()
            tokens = OAuthToken(**token_json)

            # Store tokens using the storage
            await storage.set_tokens(tokens)
            logging.info(f"[OAuth Helper] ✅ Tokens exchanged and stored successfully")

            return True, "Tokens exchanged and stored successfully"

    except Exception as e:
        logging.exception(f"[OAuth Helper] ❌ Error exchanging authorization code: {e}")
        return False, f"Token exchange failed: {str(e)}"
