"""C3+H6: every route that can raise ``ServiceUnavailableError`` must
declare HTTP 503 in its OpenAPI ``responses`` map so generated clients,
schema validators, and AsciiDoc docs match the runtime contract.

Without this declaration, the runtime returns 503 (mapped by the global
exception handler) but the OpenAPI document still advertises only the
success codes — leaving downstream consumers (curation UI client, generated
SDKs) out of sync with reality.
"""

from fastapi import FastAPI


def _responses_for(app: FastAPI, path: str, method: str) -> dict[str, object]:
    schema = app.openapi()
    return schema["paths"][path][method.lower()].get("responses", {})


class TestErsRestApiDeclares503:
    def test_resolve_declares_503(self, app: FastAPI) -> None:
        responses = _responses_for(app, "/api/v1/resolve", "post")
        assert "503" in responses, (
            f"/api/v1/resolve must declare 503 in OpenAPI; got {sorted(responses)}"
        )

    def test_resolve_bulk_declares_503(self, app: FastAPI) -> None:
        responses = _responses_for(app, "/api/v1/resolve-bulk", "post")
        assert "503" in responses, (
            f"/api/v1/resolve-bulk must declare 503 in OpenAPI; got {sorted(responses)}"
        )
