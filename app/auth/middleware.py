from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from django.contrib.auth.models import AnonymousUser, User
from django.utils.deprecation import MiddlewareMixin

from .google import verify_google_id_token, GoogleTokenError, GoogleUserInfo
from .services import UserService


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    is_authenticated: bool = True


class GoogleBearerAuthMiddleware(MiddlewareMixin):
    """
    Authenticate requests using a Google ID token provided as a Bearer token.

    - Expected header: Authorization: Bearer <id_token>
    - On success, attaches `request.user` with minimal fields and `request.auth_claims`.
    - On failure, leaves `request.user` as AnonymousUser.
    """

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
            google_info = verify_google_id_token(token)
        except GoogleTokenError as exc:
            print(f"[auth] google token verification failed: {exc}")
            request.user = getattr(request, "user", AnonymousUser())
            return None

        # Get or create Django User
        try:
            django_user, created = UserService.get_or_create_user_from_google(google_info)
            if created:
                print(f"[auth] created new user: {django_user.username} ({google_info.email})")
            else:
                print(f"[auth] authenticated existing user: {django_user.username} ({google_info.email})")
            
            # Attach Django user to request
            request.user = django_user
            request.auth_claims = {
                "sub": google_info.sub,
                "email": google_info.email,
                "email_verified": google_info.email_verified,
                "name": google_info.name,
                "picture": google_info.picture,
            }
            
        except Exception as exc:
            print(f"[auth] user creation/retrieval failed: {exc}")
            request.user = getattr(request, "user", AnonymousUser())
            return None
        
        return None

