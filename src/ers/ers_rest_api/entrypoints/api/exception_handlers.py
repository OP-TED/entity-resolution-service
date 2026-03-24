from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ers.commons.domain.exceptions import DomainError
from ers.commons.services.exceptions import ApplicationError
from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.services.exceptions import MentionNotFoundError


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers for the ERS REST API."""

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
            content={
                "error_code": ErrorCode.VALIDATION_ERROR,
                "detail": "; ".join(details),
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
                "detail": exc.message,
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
                "detail": exc.message,
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
                "detail": exc.message,
            },
        )
