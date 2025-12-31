import logging
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm, ECAlgorithm

logger = logging.getLogger(__name__)


class JWKSClient:
    """
    Helper to fetch and cache JWKS from Supabase (GoTrue).
    """

    def __init__(self, supabase_url: str):
        self.supabase_url = supabase_url
        if self.supabase_url.endswith("/"):
            self.supabase_url = self.supabase_url[:-1]

        # Standard GoTrue JWKS endpoint
        self.jwks_url = f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
        
        self._jwks_keys: Dict[str, Any] = {}
        self._last_fetch = 0
        self._cache_ttl = 3600  # 1 hour

    def get_signing_key(self, kid: Optional[str]) -> Any:
        """
        Get the signing key for a specific Key ID (kid).
        Fetches JWKS if cache is empty or expired.
        """
        if not self._jwks_keys or (time.time() - self._last_fetch > self._cache_ttl):
            self.fetch_jwks()

        if not kid:
            # Fallback if only one key exists
            if len(self._jwks_keys) == 1:
                return next(iter(self._jwks_keys.values()))
            return None

        key = self._jwks_keys.get(kid)
        if not key:
            # If key not found, try refreshing once (in case of rotation)
            self.fetch_jwks()
            key = self._jwks_keys.get(kid)

        return key

    def fetch_jwks(self):
        """
        Fetch JWKS from the provider and convert to RSA/EC keys.
        """
        try:
            logger.info(f"Fetching JWKS from {self.jwks_url}")
            # Use sync client
            with httpx.Client() as client:
                response = client.get(self.jwks_url, timeout=10.0)
                response.raise_for_status()
                jwks = response.json()

                new_keys = {}
                for key_data in jwks.get("keys", []):
                    kid = key_data.get("kid")
                    kty = key_data.get("kty")
                    
                    if kid:
                        try:
                            if kty == "RSA":
                                new_keys[kid] = RSAAlgorithm.from_jwk(key_data)
                            elif kty == "EC":
                                new_keys[kid] = ECAlgorithm.from_jwk(key_data)
                            else:
                                logger.warning(f"Unsupported key type {kty} for key {kid}")
                        except Exception as k_err:
                            logger.warning(f"Failed to parse key {kid}: {k_err}")

                self._jwks_keys = new_keys
                self._last_fetch = time.time()
                logger.info(f"Loaded {len(self._jwks_keys)} keys from JWKS")

        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            # We don't clear old keys on failure to allow surviving transient outages
            # if we already had keys.
