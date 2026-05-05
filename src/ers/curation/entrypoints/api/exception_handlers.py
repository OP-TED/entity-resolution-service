import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ers.commons.domain.exceptions import DomainError, InvalidCursorError
from ers.commons.services.exceptions import ApplicationError, NotFoundError, ServiceUnavailableError
from ers.curation.domain.errors import CurationErrorCode
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

_log = logging.getLogger(__name__)


def _format_validation_detail(exc: RequestValidationError) -> str:
    details = []
    for err in exc.errors():
        loc = " -> ".join(str(part) for part in err["loc"] if part != "body")
        msg = err["msg"]
        details.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(details)


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and application exception handlers for the Curation API."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error_code": CurationErrorCode.VALIDATION_ERROR, "message": _format_validation_detail(exc)},
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error_code": CurationErrorCode.NOT_FOUND, "message": exc.message},
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error_code": CurationErrorCode.AUTHENTICATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(UserDeactivatedError)
    async def user_deactivated_handler(request: Request, exc: UserDeactivatedError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error_code": CurationErrorCode.AUTHORIZATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error_code": CurationErrorCode.AUTHORIZATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(AlreadyCuratedError)
    async def already_curated_handler(request: Request, exc: AlreadyCuratedError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
        )

    @app.exception_handler(InvalidClusterError)
    async def invalid_cluster_handler(request: Request, exc: InvalidClusterError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
        )

    @app.exception_handler(LastAdminError)
    async def last_admin_handler(request: Request, exc: LastAdminError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
        )

    @app.exception_handler(InvalidEntityTypeError)
    async def invalid_entity_type_handler(request: Request, exc: InvalidEntityTypeError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error_code": CurationErrorCode.VALIDATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(InvalidCursorError)
    async def invalid_cursor_handler(request: Request, exc: InvalidCursorError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error_code": CurationErrorCode.VALIDATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(request: Request, exc: ServiceUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error_code": CurationErrorCode.SERVICE_UNAVAILABLE, "message": exc.message},
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error_code": CurationErrorCode.APPLICATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error_code": CurationErrorCode.APPLICATION_ERROR, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        _log.exception(
            "Unhandled error processing %s %s", request.method, request.url,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"error_code": CurationErrorCode.SERVICE_ERROR, "message": "Internal server error"},
        )
