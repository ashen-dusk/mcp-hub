from __future__ import annotations

from typing import Optional

import strawberry
from strawberry.types import Info

from app.graphql.permissions import IsAuthenticated
from app.auth.types import Me

@strawberry.type
class AuthQuery:
    @strawberry.field(permission_classes=[IsAuthenticated])
    def me(self, info: Info) -> Me:
        user = info.context.request.user
        claims = getattr(info.context.request, "auth_claims", {})
        
        return Me(
            id=str(user.id),
            email=user.email,
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name") or user.first_name or user.username,
            picture=claims.get("picture"),
        )

