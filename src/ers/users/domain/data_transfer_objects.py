from datetime import datetime

from pydantic import EmailStr, Field

from ers.commons.domain.data_transfer_objects import FrozenDTO


class RegisterRequest(FrozenDTO):
    """Request body for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(FrozenDTO):
    """Request body for user login."""

    email: str
    password: str


class TokenResponse(FrozenDTO):
    """JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(FrozenDTO):
    """Request body for token refresh."""

    refresh_token: str


class UserResponse(FrozenDTO):
    """Public user representation (no password)."""

    id: str
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime | None = None


class CreateUserRequest(FrozenDTO):
    """Admin request to create a user."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False


class UserPatchRequest(FrozenDTO):
    """Admin request to update user flags."""

    is_active: bool | None = None
    is_superuser: bool | None = None
    is_verified: bool | None = None


class UserContext(FrozenDTO):
    """Authenticated user context carried through the request lifecycle."""

    id: str
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
