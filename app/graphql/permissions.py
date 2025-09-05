from __future__ import annotations

from typing import Any

from strawberry.permission import BasePermission
from strawberry.types import Info


class IsAuthenticated(BasePermission):
    message = "Authentication required"

    def has_permission(self, source: Any, info: Info, **kwargs) -> bool:
        user = getattr(info.context.request, "user", None)
        return bool(getattr(user, "is_authenticated", False))

