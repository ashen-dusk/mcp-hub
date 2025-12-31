from __future__ import annotations

import os
from typing import Optional
from dataclasses import dataclass

from django.contrib.auth.models import AnonymousUser
from django.utils.deprecation import MiddlewareMixin

from .jwks import JWKSClient
from .services import AuthUserInfo, UserService
import jwt

class SupabaseBearerAuthMiddleware(MiddlewareMixin):
    """
    Authenticate requests using a Supabase JWT provided as a Bearer token.

    - Expected header: Authorization: Bearer <access_token>
    - On success, attaches `request.user` to the Django user.
    - On failure, leaves `request.user` to AnonymousUser.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        url: str = os.environ.get("SUPABASE_URL", "")
        # Initialize JWKS client
        self.jwks_client = JWKSClient(url)

    def process_request(self, request):
        authorization: Optional[str] = request.META.get("HTTP_AUTHORIZATION")
        if not authorization or not authorization.startswith("Bearer "):
            request.user = getattr(request, "user", AnonymousUser())
            return None

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            request.user = getattr(request, "user", AnonymousUser())
            return None

        try:
            # Decode header to find Key ID (kid)
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            # Fetch public key
            key = self.jwks_client.get_signing_key(kid)
            if not key:
                raise ValueError("Public key not found or JWKS fetch failed")

            # Verify token
            # Supabase default audience is "authenticated"
            payload = jwt.decode(
                token,
                key=key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
                leeway=60,
                options={"verify_exp": True},
            )

            # Check for email
            email = payload.get("email")
            sub = payload.get("sub")

            if not sub or not email:
                raise ValueError("No sub or email found in JWT payload")

            # Extract user info
            # Supabase stores extra metadata in user_metadata claim
            metadata = payload.get("user_metadata", {})
            
            user_info = AuthUserInfo(
                sub=sub,
                email=email,
                email_verified=metadata.get("email_verified", False) or payload.get("email_verified", False),
                name=metadata.get("full_name") or metadata.get("name") or email,
                picture=metadata.get("avatar_url") or metadata.get("picture"),
            )
            
            # Get or create Django User
            django_user, created = UserService.get_or_create_user(user_info)
            if created:
                print(f"[auth] created new user: {django_user.username} ({user_info.email})")
            else:
                pass
                # print(f"[auth] authenticated existing user: {django_user.username} ({user_info.email})")
            
            # Attach Django user to request
            request.user = django_user
            request.auth_claims = {
                "sub": user_info.sub,
                "email": user_info.email,
                "email_verified": user_info.email_verified,
                "name": user_info.name,
                "picture": user_info.picture,
            }
            
        except jwt.ExpiredSignatureError:
            print("[auth] token expired")
            request.user = getattr(request, "user", AnonymousUser())
        except jwt.PyJWTError as e:
            print(f"[auth] token decode error: {e}")
            request.user = getattr(request, "user", AnonymousUser())
        except Exception as exc:
            print(f"[auth] token verification failed: {exc}")
            request.user = getattr(request, "user", AnonymousUser())
            return None
        
        return None

