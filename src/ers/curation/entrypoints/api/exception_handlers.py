import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ers.commons.adapters.tracing import get_request_id
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


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": CurationErrorCode.VALIDATION_ERROR,
            "message": _format_validation_detail(exc),
        },
    )


async def _not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error_code": CurationErrorCode.NOT_FOUND, "message": exc.message},
    )


async def _authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error_code": CurationErrorCode.AUTHENTICATION_ERROR,
            "message": exc.message,
        },
    )


async def _user_deactivated_handler(
    request: Request, exc: UserDeactivatedError
) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error_code": CurationErrorCode.AUTHORIZATION_ERROR,
            "message": exc.message,
        },
    )


async def _authorization_error_handler(
    request: Request, exc: AuthorizationError
) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error_code": CurationErrorCode.AUTHORIZATION_ERROR,
            "message": exc.message,
        },
    )


async def _already_curated_handler(
    request: Request, exc: AlreadyCuratedError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
    )


async def _invalid_cluster_handler(
    request: Request, exc: InvalidClusterError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
    )


async def _last_admin_handler(request: Request, exc: LastAdminError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error_code": CurationErrorCode.CONFLICT, "message": exc.message},
    )


async def _invalid_entity_type_handler(
    request: Request, exc: InvalidEntityTypeError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": CurationErrorCode.VALIDATION_ERROR,
            "message": exc.message,
        },
    )


async def _invalid_cursor_handler(
    request: Request, exc: InvalidCursorError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": CurationErrorCode.VALIDATION_ERROR,
            "message": exc.message,
        },
    )


async def _service_unavailable_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error_code": CurationErrorCode.SERVICE_UNAVAILABLE,
            "message": exc.message,
        },
    )


async def _application_error_handler(
    request: Request, exc: ApplicationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": CurationErrorCode.APPLICATION_ERROR,
            "message": exc.message,
        },
    )


async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": CurationErrorCode.APPLICATION_ERROR,
            "message": exc.message,
        },
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.exception(
        "Unhandled error processing %s %s", request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": CurationErrorCode.SERVICE_ERROR,
            "message": "Internal server error",
            "request_id": get_request_id(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and application exception handlers for the Curation API."""
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(AuthenticationError, _authentication_error_handler)
    app.add_exception_handler(UserDeactivatedError, _user_deactivated_handler)
    app.add_exception_handler(AuthorizationError, _authorization_error_handler)
    app.add_exception_handler(AlreadyCuratedError, _already_curated_handler)
    app.add_exception_handler(InvalidClusterError, _invalid_cluster_handler)
    app.add_exception_handler(LastAdminError, _last_admin_handler)
    app.add_exception_handler(InvalidEntityTypeError, _invalid_entity_type_handler)
    app.add_exception_handler(InvalidCursorError, _invalid_cursor_handler)
    app.add_exception_handler(ServiceUnavailableError, _service_unavailable_handler)
    app.add_exception_handler(ApplicationError, _application_error_handler)
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
