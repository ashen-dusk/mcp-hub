from __future__ import annotations

import os
from typing import Optional
from dataclasses import dataclass

from django.contrib.auth.models import AnonymousUser
from django.utils.deprecation import MiddlewareMixin
from supabase import create_client, Client

from .services import UserService, AuthUserInfo


class SupabaseBearerAuthMiddleware(MiddlewareMixin):
    """
    Authenticate requests using a Supabase JWT provided as a Bearer token.

    - Expected header: Authorization: Bearer <access_token>
    - On success, attaches `request.user` to the Django user.
    - On failure, leaves `request.user` as AnonymousUser.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        url: str = os.environ.get("SUPABASE_URL", "")
        key: str = os.environ.get("SUPABASE_KEY", "")
        self.supabase: Client = create_client(url, key)

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
            # Verify token with Supabase
            user_response = self.supabase.auth.get_user(token)
            sb_user = user_response.user
            
            if not sb_user or not sb_user.email:
                raise ValueError("No user or email found in Supabase response")

            # Extract user info
            # Supabase stores extra metadata in user_metadata
            metadata = sb_user.user_metadata or {}
            # print(f"metadata: {metadata}, sb_user: {sb_user}")
            
            user_info = AuthUserInfo(
                sub=sb_user.id,
                email=sb_user.email,
                email_verified=metadata.get("email_verified", False),
                name=metadata.get("full_name") or metadata.get("name") or sb_user.email,
                picture=metadata.get("avatar_url") or metadata.get("picture"),
            )
            
            # Get or create Django User
            django_user, created = UserService.get_or_create_user(user_info)
            if created:
                print(f"[auth] created new user: {django_user.username} ({user_info.email})")
            else:
                print(f"[auth] authenticated existing user: {django_user.username} ({user_info.email})")
            
            # Attach Django user to request
            request.user = django_user
            request.auth_claims = {
                "sub": user_info.sub,
                "email": user_info.email,
                "email_verified": user_info.email_verified,
                "name": user_info.name,
                "picture": user_info.picture,
            }
            
        except Exception as exc:
            print(f"[auth] token verification failed: {exc}")
            request.user = getattr(request, "user", AnonymousUser())
            return None
        
        return None

