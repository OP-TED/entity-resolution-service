from typing import Annotated

from fastapi import APIRouter, Depends, status

from ers.application.auth_dtos import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from ers.application.services import AuthService
from ers.entrypoints.api.dependencies import get_auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Register a new user account."""
    return await service.register(body)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate and receive access + refresh tokens."""
    return await service.login(body)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Exchange a refresh token for a new token pair."""
    return await service.refresh(body)
