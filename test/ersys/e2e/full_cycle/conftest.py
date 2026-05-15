"""Full-cycle suite — suite-specific fixtures.

`resolved_mention` has moved to tests/e2e/conftest.py and is available to all
suites.  This file only retains fixtures that are specific to the full-cycle
batch scenarios.
"""
import pytest

from test.ersys.e2e.conftest import build_resolve_payload, poll_until


@pytest.fixture
def resolve_payload(org_group1_file1):
    """Single-mention resolve payload for full-cycle scenarios."""
    return build_resolve_payload(
        source_id="test-source-001",
        request_id="req-org1-happy-path",
        entity_type="ORGANISATION",
        content=org_group1_file1,
    )


@pytest.fixture
def resolved_mention_batch(ers_client, org_group1_file1, org_group1_file2, proc_group1_file1):
    """Submit three distinct entity mentions and poll until all are canonical.

    Returns a list of dicts with 'payload', 'response', and 'lookup' keys.
    """
    payloads = [
        build_resolve_payload("batch-source-001", "batch-request-org1", "ORGANISATION", org_group1_file1),
        build_resolve_payload("batch-source-001", "batch-request-org2", "ORGANISATION", org_group1_file2),
        build_resolve_payload("batch-source-001", "batch-request-proc1", "PROCEDURE", proc_group1_file1),
    ]

    results = []
    for payload in payloads:
        resp = ers_client.post("/api/v1/resolve", json=payload)
        resp.raise_for_status()
        results.append({"payload": payload, "response": resp.json()})

    def _all_canonical():
        canonical = []
        for item in results:
            triad = item["payload"]["mention"]["identifiedBy"]
            lookup = ers_client.get("/api/v1/lookup", params=triad)
            if lookup.status_code != 200:
                return None
            body = lookup.json()
            if not body.get("cluster_reference", {}).get("cluster_id"):
                return None
            canonical.append({**item, "lookup": body})
        return canonical if len(canonical) == len(results) else None

    try:
        return poll_until(_all_canonical, timeout_s=60.0)
    except TimeoutError:
        return results
