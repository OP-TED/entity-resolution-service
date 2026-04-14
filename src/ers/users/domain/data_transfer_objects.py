from datetime import datetime

from pydantic import EmailStr, Field

from ers.commons.domain.data_transfer_objects import FrozenDTO


class RegisterRequest(FrozenDTO):
    """Request body for user registration."""

    email: EmailStr = Field(
        description="Email address that will serve as the user's login identifier."
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (8–128 characters); stored hashed.",
    )


class LoginRequest(FrozenDTO):
    """Request body for user login."""

    email: str = Field(description="Registered email address of the user.")
    password: str = Field(description="Plain-text password for authentication.")


class TokenResponse(FrozenDTO):
    """JWT token pair response."""

    access_token: str = Field(description="Short-lived JWT used to authenticate API requests.")
    refresh_token: str = Field(description="Long-lived token used to obtain a new access token.")
    token_type: str = Field(default="bearer", description="Token scheme; always 'bearer'.")


class RefreshRequest(FrozenDTO):
    """Request body for token refresh."""

    refresh_token: str = Field(
        description="Valid refresh token previously issued by the login endpoint."
    )


class UserResponse(FrozenDTO):
    """Public user representation (no password)."""

    id: str = Field(description="Unique identifier of the user.")
    email: str = Field(description="Email address of the user.")
    is_active: bool = Field(description="Whether the user account is active and can log in.")
    is_superuser: bool = Field(description="Whether the user has superuser (admin) privileges.")
    is_verified: bool = Field(description="Whether the user's email address has been verified.")
    created_at: datetime = Field(description="Timestamp when the user account was created.")
    updated_at: datetime | None = Field(
        default=None, description="Timestamp of the last update to the user account."
    )


class CreateUserRequest(FrozenDTO):
    """Admin request to create a user."""

    email: EmailStr = Field(description="Email address for the new user account.")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Initial plain-text password (8–128 characters); stored hashed.",
    )
    is_active: bool = Field(
        default=True, description="Whether the account is active upon creation."
    )
    is_superuser: bool = Field(
        default=False, description="Grant superuser (admin) privileges to the new user."
    )
    is_verified: bool = Field(
        default=False, description="Mark the user's email as verified upon creation."
    )


class UserPatchRequest(FrozenDTO):
    """Admin request to update user flags."""

    is_active: bool | None = Field(
        default=None, description="Set to true to enable the account or false to disable it."
    )
    is_superuser: bool | None = Field(
        default=None, description="Set to true to grant or false to revoke superuser privileges."
    )
    is_verified: bool | None = Field(
        default=None, description="Set to true to mark the email as verified or false to unverify."
    )


class UserContext(FrozenDTO):
    """Authenticated user context carried through the request lifecycle."""

    id: str = Field(description="Unique identifier of the authenticated user.")
    email: str = Field(description="Email address of the authenticated user.")
    is_active: bool = Field(description="Whether the authenticated user's account is active.")
    is_superuser: bool = Field(
        description="Whether the authenticated user has superuser privileges."
    )
    is_verified: bool = Field(
        description="Whether the authenticated user's email has been verified."
    )
