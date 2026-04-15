"""Step definitions for statistics.feature.

Tests the GET /api/v1/curation/stats endpoint. Repository mocks let real
StatisticsService logic run end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from ers.curation.domain.data_transfer_objects import (
    CurationStatistics,
    RegistryStatistics,
)

FEATURE = str(Path(__file__).resolve().parent / "statistics.feature")

STATS_URL = "/api/v1/curation/stats"

ENTITY_TYPE_MAP = {
    "Organization": "ORGANISATION",
    "Person": "PERSON",
    "Procedure": "PROCEDURE",
}

POPULATED_CURATION = CurationStatistics(
    total_decisions=80,
    selected_top=40,
    selected_alternative=25,
    rejected_all=15,
)

POPULATED_REGISTRY = RegistryStatistics(
    total_entity_mentions=100,
    total_canonical_entities=50,
    average_cluster_size=2.0,
    resolution_requests=10,
)

EMPTY_CURATION = CurationStatistics(
    total_decisions=0,
    selected_top=0,
    selected_alternative=0,
    rejected_all=0,
)

EMPTY_REGISTRY = RegistryStatistics(
    total_entity_mentions=0,
    total_canonical_entities=0,
    average_cluster_size=0.0,
    resolution_requests=0,
)


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Retrieve overall statistics")
def test_retrieve_statistics():
    pass


@scenario(FEATURE, "Filter statistics by entity type")
def test_filter_by_entity_type():
    pass


@scenario(FEATURE, "Filter statistics by time window")
def test_filter_by_time_window():
    pass


@scenario(FEATURE, "Statistics with no data")
def test_empty_statistics():
    pass


@scenario(FEATURE, "Statistics are read-only")
def test_read_only():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("decisions and user actions exist in the system")
def populated_system(statistics_repository: AsyncMock) -> None:
    statistics_repository.get_curation_statistics.return_value = POPULATED_CURATION
    statistics_repository.get_registry_statistics.return_value = POPULATED_REGISTRY


@given(parsers.parse('decisions exist for entity types "{type_a}" and "{type_b}"'))
def decisions_for_types(
    ctx: dict[str, Any],
    type_a: str,
    type_b: str,
    statistics_repository: AsyncMock,
) -> None:
    statistics_repository.get_curation_statistics.return_value = POPULATED_CURATION
    statistics_repository.get_registry_statistics.return_value = POPULATED_REGISTRY


@given("user actions exist for both entity types")
def actions_for_types() -> None:
    pass


@given("user actions exist across different dates")
def actions_across_dates(statistics_repository: AsyncMock) -> None:
    statistics_repository.get_curation_statistics.return_value = POPULATED_CURATION
    statistics_repository.get_registry_statistics.return_value = POPULATED_REGISTRY


@given("no decisions or user actions exist")
def empty_system(statistics_repository: AsyncMock) -> None:
    statistics_repository.get_curation_statistics.return_value = EMPTY_CURATION
    statistics_repository.get_registry_statistics.return_value = EMPTY_REGISTRY


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator requests statistics", target_fixture="response")
def request_statistics(client: TestClient, statistics_repository: AsyncMock) -> Any:
    if not statistics_repository.get_curation_statistics.return_value.__class__.__name__.endswith(
        "Statistics"
    ):
        statistics_repository.get_curation_statistics.return_value = POPULATED_CURATION
        statistics_repository.get_registry_statistics.return_value = POPULATED_REGISTRY
    return client.get(STATS_URL)


@when(
    parsers.parse('the curator requests statistics filtered by entity type "{entity_type}"'),
    target_fixture="response",
)
def request_stats_by_type(client: TestClient, entity_type: str) -> Any:
    return client.get(
        STATS_URL, params={"entity_type": ENTITY_TYPE_MAP.get(entity_type, entity_type)}
    )


@when(
    "the curator requests statistics for a specific time range",
    target_fixture="response",
)
def request_stats_by_time(client: TestClient) -> Any:
    return client.get(
        STATS_URL,
        params={
            "timeframe_start": "2026-01-01T00:00:00Z",
            "timeframe_end": "2026-03-01T00:00:00Z",
        },
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the response includes registry statistics and curation statistics")
def includes_both_sections(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    assert "registry" in data
    assert "curation" in data


@then("registry statistics contain total entity mentions and canonical entities")
def registry_has_mentions(response: Any) -> None:
    reg = response.json()["registry"]
    assert "total_entity_mentions" in reg
    assert "total_canonical_entities" in reg


@then("registry statistics contain average cluster size and resolution request count")
def registry_has_averages(response: Any) -> None:
    reg = response.json()["registry"]
    assert "average_cluster_size" in reg
    assert "resolution_requests" in reg


@then(
    "curation statistics contain counts for accepted top, accepted alternative, and rejected all",
)
def curation_has_counts(response: Any) -> None:
    cur = response.json()["curation"]
    assert "selected_top" in cur
    assert "selected_alternative" in cur
    assert "rejected_all" in cur


@then(parsers.parse('the statistics reflect only "{entity_type}" data'))
def stats_filtered_by_type(
    response: Any,
    entity_type: str,
    statistics_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = statistics_repository.get_curation_statistics.call_args
    filters = call_args[0][0]
    assert filters.entity_type is not None


@then("the curation statistics reflect only actions within that time range")
def stats_filtered_by_time(
    response: Any,
    statistics_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = statistics_repository.get_curation_statistics.call_args
    filters = call_args[0][0]
    assert filters.timeframe_start is not None
    assert filters.timeframe_end is not None


@then("all counts are zero")
def all_counts_zero(response: Any) -> None:
    data = response.json()
    assert data["curation"]["selected_top"] == 0
    assert data["curation"]["selected_alternative"] == 0
    assert data["curation"]["rejected_all"] == 0
    assert data["registry"]["total_entity_mentions"] == 0


@then("the average cluster size is zero")
def avg_cluster_zero(response: Any) -> None:
    assert response.json()["registry"]["average_cluster_size"] == 0.0


@then("no system state is modified")
def read_only(
    statistics_repository: AsyncMock,
) -> None:
    statistics_repository.get_curation_statistics.assert_called_once()
    statistics_repository.get_registry_statistics.assert_called_once()
