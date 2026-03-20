"""Unit tests for ers.commons.adapters.redis_messages.

Tests cover the two public helpers — get_request_from_message() and
get_response_from_message() — using Pydantic model_dump_json() to produce
the raw bytes that a real Redis consumer would receive.
"""

import pytest

from erspec.models.ere import (
    ClusterReference,
    EntityMention,
    EntityMentionIdentifier,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResponse,
    EREErrorResponse,
)

from ers.commons.adapters.redis_messages import (
    get_request_from_message,
    get_response_from_message,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_request() -> EntityMentionResolutionRequest:
    return EntityMentionResolutionRequest(
        ere_request_id="req:001",
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id="DEMO",
                request_id="req",
                entity_type="ORGANISATION",
            ),
            content="<http://example.org/org1> a org:Organisation .",
            content_type="text/turtle",
        ),
    )


@pytest.fixture
def sample_response() -> EntityMentionResolutionResponse:
    return EntityMentionResolutionResponse(
        ere_request_id="req:001",
        entity_mention_id=EntityMentionIdentifier(
            source_id="DEMO",
            request_id="req",
            entity_type="ORGANISATION",
        ),
        candidates=[
            ClusterReference(cluster_id="cluster-42", confidence_score=0.95, similarity_score=0.9)
        ],
    )


@pytest.fixture
def sample_error_response() -> EREErrorResponse:
    return EREErrorResponse(
        ere_request_id="req:001",
        error_type="ers.SomeError",
        error_title="Something went wrong",
        error_detail="Detailed description of the failure.",
    )


# ---------------------------------------------------------------------------
# get_request_from_message tests
# ---------------------------------------------------------------------------


class TestGetRequestFromMessage:
    def test_returns_correct_model_instance(self, sample_request):
        raw = sample_request.model_dump_json().encode("utf-8")

        result = get_request_from_message(raw)

        assert isinstance(result, EntityMentionResolutionRequest)

    def test_preserves_ere_request_id(self, sample_request):
        raw = sample_request.model_dump_json().encode("utf-8")

        result = get_request_from_message(raw)

        assert result.ere_request_id == "req:001"

    def test_preserves_entity_mention_content(self, sample_request):
        raw = sample_request.model_dump_json().encode("utf-8")

        result = get_request_from_message(raw)

        assert result.entity_mention.content == sample_request.entity_mention.content

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            get_request_from_message(b"not-json")

    def test_raises_on_missing_type_field(self):
        raw = b'{"ere_request_id": "req:001"}'

        with pytest.raises(ValueError, match="type"):
            get_request_from_message(raw)

    def test_raises_on_unsupported_type_value(self):
        raw = b'{"type": "UnknownRequestType", "ere_request_id": "req:001"}'

        with pytest.raises(ValueError, match="Unsupported message type"):
            get_request_from_message(raw)


# ---------------------------------------------------------------------------
# get_response_from_message tests
# ---------------------------------------------------------------------------


class TestGetResponseFromMessage:
    def test_returns_correct_type_for_resolution_response(self, sample_response):
        raw = sample_response.model_dump_json().encode("utf-8")

        result = get_response_from_message(raw)

        assert isinstance(result, EntityMentionResolutionResponse)

    def test_preserves_ere_request_id_for_resolution_response(self, sample_response):
        raw = sample_response.model_dump_json().encode("utf-8")

        result = get_response_from_message(raw)

        assert result.ere_request_id == "req:001"

    def test_preserves_candidates_for_resolution_response(self, sample_response):
        raw = sample_response.model_dump_json().encode("utf-8")

        result = get_response_from_message(raw)

        assert len(result.candidates) == 1
        assert result.candidates[0].cluster_id == "cluster-42"

    def test_returns_correct_type_for_error_response(self, sample_error_response):
        raw = sample_error_response.model_dump_json().encode("utf-8")

        result = get_response_from_message(raw)

        assert isinstance(result, EREErrorResponse)

    def test_preserves_error_type_for_error_response(self, sample_error_response):
        raw = sample_error_response.model_dump_json().encode("utf-8")

        result = get_response_from_message(raw)

        assert result.error_type == "ers.SomeError"

    def test_raises_on_missing_type_field(self):
        raw = b'{"ere_request_id": "req:001"}'

        with pytest.raises(ValueError, match="type"):
            get_response_from_message(raw)

    def test_raises_on_unsupported_type_value(self):
        raw = b'{"type": "UnknownResponseType", "ere_request_id": "req:001"}'

        with pytest.raises(ValueError, match="Unsupported message type"):
            get_response_from_message(raw)
