"""C3+H6 (curation): every curation route that can raise
``ServiceUnavailableError`` must declare HTTP 503 in its OpenAPI
``responses`` map so the generated AsciiDoc matches the runtime contract.
"""

from fastapi import FastAPI


def _responses_for(app: FastAPI, path: str, method: str) -> dict[str, object]:
    schema = app.openapi()
    return schema["paths"][path][method.lower()].get("responses", {})


class TestCurationApiDeclares503:
    def test_list_decisions_declares_503(self, app: FastAPI) -> None:
        responses = _responses_for(app, "/api/v1/curation/decisions", "get")
        assert "503" in responses, (
            "GET /api/v1/curation/decisions must declare 503 in OpenAPI; "
            f"got {sorted(responses)}"
        )
