"""Unit tests for ERS REST API domain DTO validators."""

from datetime import UTC, datetime

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier
from pydantic import ValidationError

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode, ErrorResponse
from ers.ers_rest_api.domain.lookup import BulkLookupResult, RefreshBulkResponse
from ers.ers_rest_api.domain.resolution import EntityMentionResolutionResult

IDENT = EntityMentionIdentifier(
    source_id="SRC",
    request_id="req-1",
    entity_type="ORGANISATION",
)
CLUSTER = ClusterReference(
    cluster_id="cluster-1",
    confidence_score=0.9,
    similarity_score=0.8,
)
ERROR = ErrorResponse(error_code=ErrorCode.MENTION_NOT_FOUND, detail="not found")


class TestEntityMentionResolutionResultValidator:
    def test_rejects_both_success_and_error(self) -> None:
        with pytest.raises(ValidationError, match="not both or neither"):
            EntityMentionResolutionResult(
                identified_by=IDENT,
                canonical_entity_id="cluster-1",
                status=ResolutionOutcome.CANONICAL,
                error=ERROR,
            )

    def test_rejects_neither_success_nor_error(self) -> None:
        with pytest.raises(ValidationError, match="not both or neither"):
            EntityMentionResolutionResult(identified_by=IDENT)


class TestBulkLookupResultValidator:
    def test_success_fields_accepted(self) -> None:
        result = BulkLookupResult(
            identified_by=IDENT,
            cluster_reference=CLUSTER,
            last_updated=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert result.error is None

    def test_error_fields_accepted(self) -> None:
        result = BulkLookupResult(identified_by=IDENT, error=ERROR)
        assert result.cluster_reference is None

    def test_rejects_both_success_and_error(self) -> None:
        with pytest.raises(ValidationError, match="not both or neither"):
            BulkLookupResult(
                identified_by=IDENT,
                cluster_reference=CLUSTER,
                last_updated=datetime(2026, 3, 15, tzinfo=UTC),
                error=ERROR,
            )

    def test_rejects_neither_success_nor_error(self) -> None:
        with pytest.raises(ValidationError, match="not both or neither"):
            BulkLookupResult(identified_by=IDENT)


class TestRefreshBulkResponseValidator:
    def test_has_more_true_without_cursor_raises(self) -> None:
        with pytest.raises(ValidationError, match="continuation_cursor must be present"):
            RefreshBulkResponse(
                deltas=[],
                has_more=True,
                continuation_cursor=None,
            )

    def test_has_more_false_with_cursor_raises(self) -> None:
        with pytest.raises(ValidationError, match="continuation_cursor must be absent"):
            RefreshBulkResponse(
                deltas=[],
                has_more=False,
                continuation_cursor="some-cursor",
            )
