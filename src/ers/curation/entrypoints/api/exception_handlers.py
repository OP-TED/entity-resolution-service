from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ers.commons.domain.exceptions import DomainError, InvalidCursorError
from ers.commons.services.exceptions import ApplicationError, NotFoundError
from ers.curation.domain.exceptions import (
    AlreadyCuratedError,
    InvalidClusterError,
    InvalidEntityTypeError,
)
from ers.users.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    LastAdminError,
    UserDeactivatedError,
)


def _make_handler(status_code: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": getattr(exc, "message", str(exc))},
        )

    return handler


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and application exception handlers."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = []
        for err in exc.errors():
            loc = " -> ".join(str(part) for part in err["loc"] if part != "body")
            msg = err["msg"]
            details.append(f"{loc}: {msg}" if loc else msg)

        return JSONResponse(
            status_code=400,
            content={"detail": "; ".join(details)},
        )

    handlers = {
        NotFoundError: 404,
        AuthenticationError: 401,
        UserDeactivatedError: 403,
        AuthorizationError: 403,
        AlreadyCuratedError: 409,
        InvalidClusterError: 409,
        InvalidEntityTypeError: 400,
        InvalidCursorError: 400,
        LastAdminError: 409,
        ApplicationError: 400,
        DomainError: 400,
    }

    for exc_class, status_code in handlers.items():
        app.add_exception_handler(exc_class, _make_handler(status_code))
