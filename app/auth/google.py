from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


@dataclass
class GoogleUserInfo:
    sub: str
    email: str
    email_verified: bool
    name: Optional[str]
    picture: Optional[str]


class GoogleTokenError(Exception):
    pass


def verify_google_id_token(token: str, *, audience: Optional[str] = None) -> GoogleUserInfo:
    """
    Verify a Google ID token (JWT) and return basic user info.

    In production, set GOOGLE_CLIENT_ID in environment and pass as audience.
    This function raises GoogleTokenError on invalid tokens.
    """
    client_id = audience or os.getenv("GOOGLE_CLIENT_ID")
    request = google_requests.Request()
    try:
        claims: Dict[str, Any] = id_token.verify_oauth2_token(token, request, audience=client_id)
    except Exception as exc:  # keep broad to wrap google-auth exceptions
        raise GoogleTokenError(str(exc))

    # Basic claim validations
    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = bool(claims.get("email_verified", False))
    name = claims.get("name")
    picture = claims.get("picture")

    if not sub or not email:
        raise GoogleTokenError("Token missing required claims")

    return GoogleUserInfo(
        sub=sub,
        email=email,
        email_verified=email_verified,
        name=name,
        picture=picture,
    )

