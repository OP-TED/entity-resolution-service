"""H1: ``CurationErrorResponse`` schema tests.

Asserts that the curation API error envelope declares the ``request_id`` field
so the OpenAPI schema matches the payload emitted by the unhandled-error
handler in ``curation/entrypoints/api/exception_handlers.py``.
"""

from ers.curation.domain.errors import CurationErrorCode, CurationErrorResponse


class TestCurationErrorResponseSchema:
    def test_request_id_defaults_to_none(self) -> None:
        err = CurationErrorResponse(
            error_code=CurationErrorCode.SERVICE_ERROR, message="boom"
        )
        assert err.request_id is None

    def test_request_id_is_assignable(self) -> None:
        err = CurationErrorResponse(
            error_code=CurationErrorCode.SERVICE_ERROR,
            message="boom",
            request_id="req-curation-9",
        )
        assert err.request_id == "req-curation-9"

    def test_request_id_appears_in_json_schema(self) -> None:
        schema = CurationErrorResponse.model_json_schema()
        assert "request_id" in schema["properties"]
