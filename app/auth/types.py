from __future__ import annotations

from typing import Optional

import strawberry


@strawberry.type
class Me:
    id: str
    email: str
    email_verified: bool
    name: Optional[str]
    picture: Optional[str]
    provider: str = "google"