from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ers.commons.domain.exceptions import DomainError, InvalidCursorError
from ers.commons.services.exceptions import ApplicationError, NotFoundError
from ers.curation.domain.exceptions import (
    AlreadyCuratedError,
    InvalidClusterError,
)
from ers.users.domain.exceptions import AuthenticationError, AuthorizationError, LastAdminError


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and application exception handlers."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(
        request: Request,
        exc: NotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.message},
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request,
        exc: AuthenticationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": exc.message},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(
        request: Request,
        exc: AuthorizationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": exc.message},
        )

    @app.exception_handler(AlreadyCuratedError)
    async def already_curated_handler(
        request: Request,
        exc: AlreadyCuratedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": exc.message},
        )

    @app.exception_handler(InvalidClusterError)
    async def invalid_cluster_handler(
        request: Request,
        exc: InvalidClusterError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": exc.message},
        )

    @app.exception_handler(InvalidCursorError)
    async def invalid_cursor_handler(
        request: Request,
        exc: InvalidCursorError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message},
        )

    @app.exception_handler(LastAdminError)
    async def last_admin_handler(
        request: Request,
        exc: LastAdminError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": exc.message},
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message},
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message},
        )
