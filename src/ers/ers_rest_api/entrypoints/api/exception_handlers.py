import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers for the ERS REST API."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": ErrorCode.VALIDATION_ERROR,
                "message": _format_validation_detail(exc),
            },
        )

    @app.exception_handler(ParsingFailedError)
    async def parsing_failed_handler(
        request: Request,
        exc: ParsingFailedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": ErrorCode.PARSING_FAILED,
                "message": exc.message,
            },
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        request: Request,
        exc: IdempotencyConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error_code": ErrorCode.IDEMPOTENCY_CONFLICT,
                "message": exc.message,
            },
        )

    @app.exception_handler(MentionNotFoundError)
    async def mention_not_found_handler(
        request: Request,
        exc: MentionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error_code": ErrorCode.MENTION_NOT_FOUND,
                "message": exc.message,
            },
        )

    @app.exception_handler(SourceNotFoundError)
    async def source_not_found_handler(
        request: Request,
        exc: SourceNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error_code": ErrorCode.SOURCE_NOT_FOUND,
                "message": exc.message,
            },
        )

    @app.exception_handler(ResolutionTimeoutError)
    async def resolution_timeout_handler(
        request: Request,
        exc: ResolutionTimeoutError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content={
                "error_code": ErrorCode.SERVICE_TIMEOUT,
                "message": exc.message,
            },
        )

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(
        request: Request,
        exc: ServiceUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error_code": ErrorCode.SERVICE_UNAVAILABLE,
                "message": exc.message,
            },
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": ErrorCode.VALIDATION_ERROR,
                "message": exc.message,
            },
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": ErrorCode.VALIDATION_ERROR,
                "message": exc.message,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        _log.exception(
            "Unhandled error processing %s %s", request.method, request.url,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error_code": ErrorCode.SERVICE_ERROR,
                "message": "Internal server error",
            },
        )
