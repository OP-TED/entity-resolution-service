from datetime import datetime

from pydantic import BaseModel


class User(BaseModel):
    """Local user account for authentication and authorization."""

    id: str
    email: str
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    created_at: datetime
    updated_at: datetime | None = None
