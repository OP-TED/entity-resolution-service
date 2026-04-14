from typing import Annotated

from fastapi import APIRouter, Depends, status

from ers.curation.entrypoints.api.dependencies import get_auth_service
from ers.curation.entrypoints.api.v1.schemas import ErrorResponse
from ers.users.domain.data_transfer_objects import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from ers.users.services import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def register(
    body: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Register a new user account."""
    return await service.register(body)


@router.post(
    "/login",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "User account is deactivated"},
    },
)
async def login(
    body: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate and receive access + refresh tokens."""
    return await service.login(body)


@router.post(
    "/refresh",
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def refresh(
    body: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Exchange a refresh token for a new token pair."""
    return await service.refresh(body)
