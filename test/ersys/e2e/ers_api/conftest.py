"""ERS API boundary suite — suite-specific payload fixtures.

Payload fixtures use distinct source_id/request_id pairs per scenario group so
scenarios that run in sequence cannot pollute each other's request registry.

Cross-suite helpers (build_resolve_payload, derive_provisional_id,
wait_for_canonical) live in tests/e2e/conftest.py and are available to all
suites without an explicit import in test files.
"""
import pytest

from test.ersys.e2e.conftest import build_resolve_payload, derive_provisional_id  # re-export for test files

__all__ = ["derive_provisional_id"]  # test files import derive_provisional_id from here


# ---------------------------------------------------------------------------
# Resolve-scenario payloads — canonical resolution and idempotency tests
# ---------------------------------------------------------------------------

@pytest.fixture
def resolve_payload(org_group1_file1: str) -> dict:
    """Correctly-nested resolve payload for canonical / idempotency scenarios.

    Triad: source=test-source-resolve / request=test-request-001 / ORGANISATION
    """
    return build_resolve_payload(
        source_id="test-source-resolve",
        request_id="test-request-001",
        entity_type="ORGANISATION",
        content=org_group1_file1,
    )


@pytest.fixture
def alternative_payload(org_group1_file2: str) -> dict:
    """Different content for the same triad — idempotency conflict tests."""
    return build_resolve_payload(
        source_id="test-source-resolve",
        request_id="test-request-001",
        entity_type="ORGANISATION",
        content=org_group1_file2,
    )


# ---------------------------------------------------------------------------
# Lookup-scenario payloads — isolated triads for cluster_assignment_lookup tests
# ---------------------------------------------------------------------------

@pytest.fixture
def lookup_resolve_payload(org_group1_file1: str) -> dict:
    """Resolve payload for the single-lookup resolved-mention scenario.

    Triad: source=test-source-lookup / request=lookup-req-001 / ORGANISATION
    """
    return build_resolve_payload(
        source_id="test-source-lookup",
        request_id="lookup-req-001",
        entity_type="ORGANISATION",
        content=org_group1_file1,
    )


@pytest.fixture
def refresh_bulk_payload_1(org_group1_file1: str) -> dict:
    """First mention for refresh-bulk tests (source test-source-001)."""
    return build_resolve_payload(
        source_id="test-source-001",
        request_id="refresh-req-001",
        entity_type="ORGANISATION",
        content=org_group1_file1,
    )


@pytest.fixture
def refresh_bulk_payload_2(org_group1_file2: str) -> dict:
    """Second mention for refresh-bulk tests (source test-source-001)."""
    return build_resolve_payload(
        source_id="test-source-001",
        request_id="refresh-req-002",
        entity_type="ORGANISATION",
        content=org_group1_file2,
    )


@pytest.fixture
def refresh_bulk_payload_source2(org_group1_file1: str) -> dict:
    """Mention for the no-updates refresh-bulk scenario (source test-source-002)."""
    return build_resolve_payload(
        source_id="test-source-002",
        request_id="refresh-req-s2-001",
        entity_type="ORGANISATION",
        content=org_group1_file1,
    )
