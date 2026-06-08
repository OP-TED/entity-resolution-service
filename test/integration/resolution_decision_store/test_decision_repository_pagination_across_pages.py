"""Pagination-across-pages integration coverage (the test class missing from
TEDSWS-524-1 that lets C1 / A3 ship unnoticed).

For each combination of ``(ever_reviewed, reviewed_since_placement)`` and each
sort direction, the union of all pages obtained via ``next_cursor`` must equal
the unpaged scan of the same filter — proving:

- the keyset cursor advances correctly across boundaries,
- no row is duplicated across pages,
- ``CursorPage.count`` matches the size of that union (resolves A3),
- pagination never under-fills (every page returns exactly ``per_page`` rows
  until the final page).
"""

from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorParams, DecisionOrdering
from ers.curation.domain.data_transfer_objects import DecisionFilters
from ers.resolution_decision_store.adapters.cluster_size_index import (
    MongoClusterSizeIndex,
)
from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)

_T0 = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)


def _ident(source_id: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id, request_id="r1", entity_type="Person"
    )


def _cluster(cluster_id: str = "c-1") -> ClusterReference:
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.8
    )


@pytest.fixture()
async def repo(mongo_db):
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    return r


@pytest.fixture()
async def seeded(repo):
    """50 decisions split across the four review-state partitions.

    Layout: ids 0–11 ``rev``, 12–25 ``revisit``, 26–37 ``up_to_date``, 38–49 ``never``.

    - ``rev``         : counter>0, flag=True   → ever=True,  since=True
    - ``revisit``     : counter>0, flag=False  → ever=True,  since=False (needs revisit)
    - ``up_to_date``  : counter>0, flag=True   → ever=True,  since=True (alias of ``rev``;
                       split for index/partition realism)
    - ``never``       : counter=0, flag=False  → ever=False, since=False
    """
    ids_by_partition = {"rev": [], "revisit": [], "up_to_date": [], "never": []}
    partition_for = (
        ["rev"] * 12 + ["revisit"] * 14 + ["up_to_date"] * 12 + ["never"] * 12
    )

    for i, partition in enumerate(partition_for):
        ts = _T0 + timedelta(seconds=i)
        decision = await repo.upsert_decision(
            _ident(f"s-{i:03d}"), _cluster(f"c-{i:03d}"), [], ts
        )
        if partition in ("rev", "up_to_date"):
            await repo.record_review(decision.id, ts + timedelta(seconds=1))
        elif partition == "revisit":
            await repo.record_review(decision.id, ts + timedelta(seconds=1))
            # Material placement advance resets the flag.
            await repo.upsert_decision(
                _ident(f"s-{i:03d}"),
                _cluster(f"c-{i:03d}-bumped"),
                [],
                ts + timedelta(seconds=5),
            )
        ids_by_partition[partition].append(decision.id)

    return ids_by_partition


async def _scan(
    repo, *, per_page: int, ordering=None, **filter_kwargs
) -> tuple[list[str], list[int]]:
    """Page across all results using ``next_cursor``. Return (ids, counts)."""
    ids: list[str] = []
    counts: list[int] = []
    cursor: str | None = None
    while True:
        page = await repo.find_with_filters(
            filters=DecisionFilters(ordering=ordering),
            cursor_params=CursorParams(cursor=cursor, limit=per_page),
            **filter_kwargs,
        )
        ids.extend(d.id for d in page.results)
        counts.append(page.count)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return ids, counts


async def _unpaged(repo, *, ordering=None, **filter_kwargs) -> list[str]:
    page = await repo.find_with_filters(
        filters=DecisionFilters(ordering=ordering),
        cursor_params=CursorParams(limit=10_000),
        **filter_kwargs,
    )
    return [d.id for d in page.results]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "filter_kwargs",
    [
        {},
        {"ever_reviewed": True},
        {"ever_reviewed": False},
        {"reviewed_since_placement": True},
        {"reviewed_since_placement": False},
        {"ever_reviewed": True, "reviewed_since_placement": False},  # needs revisit
        {
            "ever_reviewed": True,
            "reviewed_since_placement": True,
        },  # reviewed + up to date
    ],
    ids=[
        "no_filter",
        "ever_reviewed_true",
        "ever_reviewed_false",
        "reviewed_since_placement_true",
        "reviewed_since_placement_false",
        "needs_revisit",
        "up_to_date",
    ],
)
async def test_paginated_union_matches_unpaged_and_count(repo, seeded, filter_kwargs):
    """For every filter combination, page-by-page union equals the unpaged scan
    and ``count`` matches the union size exactly."""
    per_page = 5
    paged_ids, counts = await _scan(repo, per_page=per_page, **filter_kwargs)
    unpaged_ids = await _unpaged(repo, **filter_kwargs)

    assert paged_ids == unpaged_ids, "paginated traversal must match the unpaged scan"
    assert len(set(paged_ids)) == len(paged_ids), "no row may appear on two pages"
    assert all(c == len(unpaged_ids) for c in counts), (
        "CursorPage.count must equal the filtered-set size on every page (A3)"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pagination_under_fills_only_on_final_page(repo, seeded):
    """Every page except the last must contain exactly per_page rows."""
    per_page = 7
    cursor: str | None = None
    pages: list[int] = []
    while True:
        page = await repo.find_with_filters(
            filters=DecisionFilters(),
            cursor_params=CursorParams(cursor=cursor, limit=per_page),
            reviewed_since_placement=False,
        )
        pages.append(len(page.results))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert all(p == per_page for p in pages[:-1]), (
        f"non-terminal pages must be full ({per_page}); got {pages}"
    )
    assert pages[-1] <= per_page


# ── cluster_size sort pagination (M2 / C1 regression) ─────────────────────────


@pytest.fixture()
async def seeded_with_cluster_sizes(repo, mongo_db):
    """20 decisions distributed across 5 clusters of varying sizes (1, 2, 3, 5, 9).

    Total cluster-size sum equals the decision count so the cluster_sizes
    projection is internally consistent. Each decision is placed in exactly
    one cluster; ``cluster_sizes`` is populated alongside via the index.
    """
    size_layout: list[tuple[str, int]] = [
        ("cs-1", 1),
        ("cs-2", 2),
        ("cs-3", 3),
        ("cs-5", 5),
        ("cs-9", 9),
    ]
    index = MongoClusterSizeIndex(mongo_db)

    ids_by_cluster: dict[str, list[str]] = {}
    counter = 0
    for cluster_id, size in size_layout:
        for _ in range(size):
            ts = _T0 + timedelta(seconds=counter)
            decision = await repo.upsert_decision(
                _ident(f"cs-s-{counter:03d}"), _cluster(cluster_id), [], ts
            )
            await index.shift(from_cluster=None, to_cluster=cluster_id)
            ids_by_cluster.setdefault(cluster_id, []).append(decision.id)
            counter += 1

    return {
        "ids_by_cluster": ids_by_cluster,
        "sizes": dict(size_layout),
        "total": counter,
    }


async def _scan_cluster_size(
    repo, *, per_page: int, ordering: DecisionOrdering
) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    while True:
        page = await repo.find_with_filters(
            filters=DecisionFilters(ordering=ordering),
            cursor_params=CursorParams(cursor=cursor, limit=per_page),
        )
        ids.extend(d.id for d in page.results)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return ids


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "ordering",
    [DecisionOrdering.CLUSTER_SIZE_DESC, DecisionOrdering.CLUSTER_SIZE_ASC],
    ids=["cluster_size_desc", "cluster_size_asc"],
)
async def test_cluster_size_sort_paginates_across_pages(
    repo, seeded_with_cluster_sizes, ordering
):
    """C1 regression: paginating with cluster_size sort across multiple pages
    must return the same set as an unpaged scan, with no row duplicated and
    no row dropped. On `hotfix/TEDSWS-524-1`, page 2+ returned empty because
    the cursor predicate landed in stage 1 before $addFields cluster_size."""
    per_page = 4  # forces 5 pages over 20 decisions
    paged_ids = await _scan_cluster_size(repo, per_page=per_page, ordering=ordering)

    unpaged = await repo.find_with_filters(
        filters=DecisionFilters(ordering=ordering),
        cursor_params=CursorParams(limit=10_000),
    )
    unpaged_ids = [d.id for d in unpaged.results]

    assert paged_ids == unpaged_ids, (
        "paginated cluster_size traversal must match the unpaged scan exactly"
    )
    assert len(paged_ids) == seeded_with_cluster_sizes["total"], (
        "every seeded decision must appear in the paginated scan"
    )
    assert len(set(paged_ids)) == len(paged_ids), "no row may appear on two pages"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cluster_size_sort_pages_do_not_under_fill(
    repo, seeded_with_cluster_sizes
):
    """Every non-terminal page must be full when sorting by cluster_size — the
    cursor predicate runs in the post-$addFields $match before $limit, so
    pagination cannot under-fill."""
    per_page = 6  # 20 rows / 6 → pages of 6, 6, 6, 2
    cursor: str | None = None
    page_sizes: list[int] = []
    while True:
        page = await repo.find_with_filters(
            filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
            cursor_params=CursorParams(cursor=cursor, limit=per_page),
        )
        page_sizes.append(len(page.results))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert all(p == per_page for p in page_sizes[:-1]), (
        f"non-terminal pages must be full ({per_page}); got {page_sizes}"
    )
    assert page_sizes[-1] <= per_page
