import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ers.commons.adapters.tracing import get_request_id
from ers.commons.domain.exceptions import DomainError
from ers.commons.services.exceptions import ApplicationError, ServiceUnavailableError
from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from ers.request_registry.services.exceptions import IdempotencyConflictError
from ers.resolution_coordinator.domain.exceptions import (
    ParsingFailedError,
    ResolutionTimeoutError,
    SourceNotFoundError,
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
            "error_code": ErrorCode.VALIDATION_ERROR,
            "message": _format_validation_detail(exc),
        },
    )


async def _parsing_failed_handler(
    request: Request, exc: ParsingFailedError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error_code": ErrorCode.PARSING_FAILED, "message": exc.message},
    )


async def _idempotency_conflict_handler(
    request: Request, exc: IdempotencyConflictError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error_code": ErrorCode.IDEMPOTENCY_CONFLICT, "message": exc.message},
    )


async def _mention_not_found_handler(
    request: Request, exc: MentionNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error_code": ErrorCode.MENTION_NOT_FOUND, "message": exc.message},
    )


async def _source_not_found_handler(
    request: Request, exc: SourceNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error_code": ErrorCode.SOURCE_NOT_FOUND, "message": exc.message},
    )


async def _resolution_timeout_handler(
    request: Request, exc: ResolutionTimeoutError
) -> JSONResponse:
    return JSONResponse(
        status_code=504,
        content={"error_code": ErrorCode.SERVICE_TIMEOUT, "message": exc.message},
    )


async def _service_unavailable_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error_code": ErrorCode.SERVICE_UNAVAILABLE, "message": exc.message},
    )


async def _application_error_handler(
    request: Request, exc: ApplicationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error_code": ErrorCode.APPLICATION_ERROR, "message": exc.message},
    )


async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error_code": ErrorCode.APPLICATION_ERROR, "message": exc.message},
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.exception(
        "Unhandled error processing %s %s", request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": ErrorCode.SERVICE_ERROR,
            "message": "Internal server error",
            "request_id": get_request_id(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers for the ERS REST API."""
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(ParsingFailedError, _parsing_failed_handler)
    app.add_exception_handler(IdempotencyConflictError, _idempotency_conflict_handler)
    app.add_exception_handler(MentionNotFoundError, _mention_not_found_handler)
    app.add_exception_handler(SourceNotFoundError, _source_not_found_handler)
    app.add_exception_handler(ResolutionTimeoutError, _resolution_timeout_handler)
    app.add_exception_handler(ServiceUnavailableError, _service_unavailable_handler)
    app.add_exception_handler(ApplicationError, _application_error_handler)
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
