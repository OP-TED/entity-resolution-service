"""Step definitions for canonical_entity_preview.feature.

Tests the proposed and alternative canonical entity endpoints through
the FastAPI test client. Repository mocks let real CanonicalEntityService
logic run end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
)

FEATURE = str(Path(__file__).resolve().parent / "canonical_entity_preview.feature")

DECISIONS_URL = "/api/v1/curation/decisions"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "View the proposed canonical entity for a decision")
def test_proposed_entity():
    pass


@scenario(FEATURE, "Proposed canonical entity for a non-existent decision")
def test_proposed_not_found():
    pass


@scenario(FEATURE, "View alternative canonical entities for a decision")
def test_alternatives():
    pass


@scenario(FEATURE, "Alternative canonical entities with pagination")
def test_alternatives_paginated():
    pass


@scenario(FEATURE, "Decision with no alternative candidates")
def test_no_alternatives():
    pass


@scenario(FEATURE, "Alternative canonical entities for a non-existent decision")
def test_alternatives_not_found():
    pass


@scenario(FEATURE, "Canonical entity preview with mentions lacking parsed representations")
def test_preview_missing_representations():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_cluster_mentions(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
    n_mentions: int = 3,
) -> None:
    """Wire repository mocks so _build_canonical_entity_preview works."""
    identifiers = EntityMentionIdentifierFactory.batch(n_mentions)
    mentions = [EntityMentionFactory.build(identifiedBy=eid) for eid in identifiers]
    decision_repository.find_mention_ids_by_cluster.return_value = identifiers
    entity_mention_repository.find_by_identifiers.return_value = mentions


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse('a decision exists with a current placement in cluster "{cluster_id}"'),
)
def decision_with_placement(
    ctx: dict[str, Any],
    cluster_id: str,
    decision_repository: AsyncMock,
) -> None:
    placement = ClusterReferenceFactory.build(
        cluster_id=cluster_id,
        confidence_score=0.9,
        similarity_score=0.85,
    )
    decision = DecisionFactory.build(id="decision-1", current_placement=placement)
    decision_repository.find_by_id.return_value = decision
    ctx["decision_id"] = "decision-1"
    ctx["cluster_id"] = cluster_id


@given(parsers.parse('cluster "{cluster_id}" contains {count:d} entity mentions'))
def cluster_has_mentions(
    ctx: dict[str, Any],
    cluster_id: str,
    count: int,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_cluster_mentions(decision_repository, entity_mention_repository, count)


@given(parsers.parse("a decision exists with {count:d} candidate clusters"))
def decision_with_n_candidates(
    ctx: dict[str, Any],
    count: int,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    current = ClusterReferenceFactory.build(cluster_id="cluster-0")
    candidates = [current] + [
        ClusterReferenceFactory.build(cluster_id=f"cluster-{i}") for i in range(1, count)
    ]
    decision = DecisionFactory.build(
        id="decision-1",
        current_placement=current,
        candidates=candidates,
    )
    decision_repository.find_by_id.return_value = decision
    _setup_cluster_mentions(decision_repository, entity_mention_repository)
    ctx["decision_id"] = "decision-1"
    ctx["candidate_count"] = count


@given("the current placement is in the first candidate")
def current_is_first() -> None:
    pass


@given(
    parsers.parse("a decision exists with {count:d} candidate clusters including the current"),
)
def decision_with_candidates_and_current(
    ctx: dict[str, Any],
    count: int,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    current = ClusterReferenceFactory.build(cluster_id="cluster-0")
    candidates = [current] + [
        ClusterReferenceFactory.build(cluster_id=f"cluster-{i}") for i in range(1, count)
    ]
    decision = DecisionFactory.build(
        id="decision-1",
        current_placement=current,
        candidates=candidates,
    )
    decision_repository.find_by_id.return_value = decision
    _setup_cluster_mentions(decision_repository, entity_mention_repository)
    ctx["decision_id"] = "decision-1"
    ctx["candidate_count"] = count


@given(
    "a decision exists with only 1 candidate cluster (the current placement)",
)
def decision_single_candidate(
    ctx: dict[str, Any],
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    current = ClusterReferenceFactory.build(cluster_id="cluster-0")
    decision = DecisionFactory.build(
        id="decision-1",
        current_placement=current,
        candidates=[current],
    )
    decision_repository.find_by_id.return_value = decision
    _setup_cluster_mentions(decision_repository, entity_mention_repository)
    ctx["decision_id"] = "decision-1"


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator requests the proposed canonical entity", target_fixture="response")
def request_proposed(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.get(
        f"{DECISIONS_URL}/{ctx['decision_id']}/proposed-canonical-entity",
    )


@when(
    "the curator requests the proposed canonical entity for a non-existent decision",
    target_fixture="response",
)
def request_proposed_not_found(
    client: TestClient,
    decision_repository: AsyncMock,
) -> Any:
    decision_repository.find_by_id.return_value = None
    return client.get(
        f"{DECISIONS_URL}/nonexistent/proposed-canonical-entity",
    )


@when(
    "the curator requests alternative canonical entities",
    target_fixture="response",
)
def request_alternatives(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.get(
        f"{DECISIONS_URL}/{ctx['decision_id']}/alternative-canonical-entities",
    )


@when(
    parsers.parse(
        "the curator requests alternative canonical entities for page {page:d} "
        "with {per_page:d} items per page"
    ),
    target_fixture="response",
)
def request_alternatives_paginated(
    client: TestClient,
    ctx: dict[str, Any],
    page: int,
    per_page: int,
) -> Any:
    return client.get(
        f"{DECISIONS_URL}/{ctx['decision_id']}/alternative-canonical-entities",
        params={"page": page, "per_page": per_page},
    )


@when(
    "the curator requests alternative canonical entities for a non-existent decision",
    target_fixture="response",
)
def request_alternatives_not_found(
    client: TestClient,
    decision_repository: AsyncMock,
) -> Any:
    decision_repository.find_by_id.return_value = None
    return client.get(
        f"{DECISIONS_URL}/nonexistent/alternative-canonical-entities",
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse('a preview is returned for cluster "{cluster_id}"'))
def preview_returned(response: Any, cluster_id: str) -> None:
    assert response.status_code == 200
    assert response.json()["cluster_id"] == cluster_id


@then(
    parsers.parse("the preview includes up to {limit:d} top entity mentions from the cluster"),
)
def preview_has_entities(response: Any, limit: int) -> None:
    entities = response.json()["top_entities"]
    assert len(entities) <= limit
    assert len(entities) > 0


@then(parsers.parse("{count:d} alternative entity previews are returned"))
def n_alternatives_returned(response: Any, count: int) -> None:
    assert response.status_code == 200
    assert len(response.json()["results"]) == count


@then("each preview includes the cluster identifier and top entity mentions")
def alternative_preview_fields(response: Any) -> None:
    for item in response.json()["results"]:
        assert "cluster_id" in item
        assert "top_entities" in item


@then(parsers.parse("{count:d} alternative previews are returned"))
def n_alt_previews_returned(response: Any, count: int) -> None:
    assert response.status_code == 200
    assert len(response.json()["results"]) == count


@then("a next page indicator is present")
def next_page_present(response: Any) -> None:
    assert response.json()["next"] is not None


@then("an empty result set is returned")
def empty_results(response: Any) -> None:
    assert response.status_code == 200
    assert response.json()["results"] == []


@then("the system responds with a not found error")
def not_found(response: Any) -> None:
    assert response.status_code == 404


# --- Incomplete data ---


@given(
    parsers.parse('cluster "{cluster_id}" contains entity mentions with no parsed representations'),
)
def cluster_has_mentions_without_parsed(
    ctx: dict[str, Any],
    cluster_id: str,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    identifiers = EntityMentionIdentifierFactory.batch(3)
    mentions = [
        EntityMentionFactory.build(identifiedBy=eid, parsed_representation=None)
        for eid in identifiers
    ]
    decision_repository.find_mention_ids_by_cluster.return_value = identifiers
    entity_mention_repository.find_by_identifiers.return_value = mentions


@then(
    "the preview includes only the entity mention identifiers where parsed representations are absent",
)
def preview_shows_identifiers_only(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    for entity in data.get("top_entities", []):
        assert "identified_by" in entity
        assert entity["parsed_representation"] is None
