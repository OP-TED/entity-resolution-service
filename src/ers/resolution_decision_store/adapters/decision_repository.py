from abc import abstractmethod
from datetime import datetime
from typing import Any

import pymongo
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from opentelemetry import trace
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure

from ers.commons.adapters.decision_repository import (
    BaseDecisionRepository,
    BaseMongoDecisionRepository,
)
from ers.commons.domain.cursor import decode_cursor, encode_cursor
from ers.commons.domain.data_transfer_objects import (
    CursorPage,
    CursorParams,
    DecisionFilters,
    DecisionOrdering,
)
from ers.resolution_decision_store.adapters.provisional_id import (
    derive_provisional_cluster_id,
)
from ers.resolution_decision_store.domain.errors import (
    RepositoryConnectionError,
    RepositoryOperationError,
    StaleOutcomeError,
)

# MongoDB document field paths
_FIELD_SOURCE_ID = "about_entity_mention.source_id"
_FIELD_ENTITY_TYPE = "about_entity_mention.entity_type"
_FIELD_CONFIDENCE = "current_placement.confidence_score"
_FIELD_SIMILARITY = "current_placement.similarity_score"
_FIELD_CLUSTER_ID = "current_placement.cluster_id"
_FIELD_ABOUT_ENTITY_MENTION = "about_entity_mention"
_FIELD_CREATED_AT = "created_at"
_FIELD_UPDATED_AT = "updated_at"


class DecisionRepository(BaseDecisionRepository):
    """Repository for decision projection persistence and curation specific querying."""

    @abstractmethod
    async def find_with_filters(
        self,
        filters: DecisionFilters | None = None,
        cursor_params: CursorParams | None = None,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> CursorPage[Decision]:
        """Find decisions with optional filtering and cursor-based pagination.

        Supports both filtered curation queries and unfiltered bulk traversal.

        Args:
            filters: Optional filter criteria. None for unfiltered traversal.
            cursor_params: Cursor-based pagination parameters (cursor, limit).
                Defaults to CursorParams() if None.
            mention_identifiers: When provided, restricts results to decisions
                whose ``about_entity_mention`` is in this list (used for
                full-text search pre-filtering).
        """

    @abstractmethod
    async def find_mention_ids_by_cluster(
        self,
        cluster_id: str,
        limit: int,
    ) -> list[EntityMentionIdentifier]:
        """Return entity mention identifiers for decisions placed in a cluster."""

    @abstractmethod
    async def count_distinct_clusters(self) -> int:
        """Return the number of distinct cluster IDs across all decisions."""

    @abstractmethod
    async def average_cluster_size(self) -> float:
        """Return the average number of decisions per cluster."""

    @abstractmethod
    async def find_delta_for_source(
        self,
        source_id: str,
        updated_since: datetime | None,
        cursor_params: CursorParams | None = None,
    ) -> CursorPage[Decision]:
        """Return decisions for a source changed after updated_since, cursor-paginated.

        Args:
            source_id: Filter to this source system.
            updated_since: Return decisions with updated_at > this value, or all if None.
            cursor_params: Pagination parameters (cursor, limit).

        Returns:
            A CursorPage with matching decisions and an optional next_cursor.
            ``count`` is always 0 — no total-count query is performed.
        """


class MongoDecisionRepository(
    BaseMongoDecisionRepository,
    DecisionRepository,
):
    """MongoDB repository for decision projections with curation-specific queries."""

    _SORT_FIELD_MAP: dict[DecisionOrdering, tuple[str, bool]] = {
        DecisionOrdering.CONFIDENCE_ASC: (_FIELD_CONFIDENCE, True),
        DecisionOrdering.CONFIDENCE_DESC: (_FIELD_CONFIDENCE, False),
        DecisionOrdering.CREATED_AT_ASC: (_FIELD_CREATED_AT, True),
        DecisionOrdering.CREATED_AT_DESC: (_FIELD_CREATED_AT, False),
        DecisionOrdering.UPDATED_AT_ASC: (_FIELD_UPDATED_AT, True),
        DecisionOrdering.UPDATED_AT_DESC: (_FIELD_UPDATED_AT, False),
    }

    def _build_query(self, filters: DecisionFilters) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if filters.source_id is not None:
            query[_FIELD_SOURCE_ID] = filters.source_id

        if filters.updated_since is not None:
            query[_FIELD_UPDATED_AT] = {"$gt": filters.updated_since}

        if filters.entity_type is not None:
            query[_FIELD_ENTITY_TYPE] = filters.entity_type

        placement_range: dict[str, dict[str, float]] = {}
        if filters.confidence_min is not None:
            placement_range.setdefault(_FIELD_CONFIDENCE, {})["$gte"] = filters.confidence_min
        if filters.confidence_max is not None:
            placement_range.setdefault(_FIELD_CONFIDENCE, {})["$lte"] = filters.confidence_max
        if filters.similarity_min is not None:
            placement_range.setdefault(_FIELD_SIMILARITY, {})["$gte"] = filters.similarity_min
        if filters.similarity_max is not None:
            placement_range.setdefault(_FIELD_SIMILARITY, {})["$lte"] = filters.similarity_max
        query.update(placement_range)

        return query

    def _get_sort_info(self, ordering: DecisionOrdering | None) -> tuple[str, bool]:
        """Return (mongo_field_name, is_ascending) for the given ordering."""
        if ordering is None:
            return _FIELD_CREATED_AT, False
        return self._SORT_FIELD_MAP[ordering]

    def _build_sort(self, ordering: DecisionOrdering | None) -> list[tuple[str, int]]:
        field, ascending = self._get_sort_info(ordering)
        direction = 1 if ascending else -1
        return [(field, direction), ("_id", direction)]

    def _extract_sort_value(self, decision: Decision, sort_field: str) -> float | datetime | None:
        if sort_field == _FIELD_CONFIDENCE:
            return decision.current_placement.confidence_score
        if sort_field == _FIELD_CREATED_AT:
            return decision.created_at
        if sort_field == _FIELD_UPDATED_AT:
            return decision.updated_at
        return None

    async def _fetch_existing_and_raise_stale(
        self,
        triad_hash: str,
        identifier: EntityMentionIdentifier,
        updated_at: datetime,
        cause: Exception | None = None,
    ) -> None:
        """Fetch existing doc and raise StaleOutcomeError if it exists."""
        existing = await self._collection.find_one({"_id": triad_hash})
        if existing:
            raise StaleOutcomeError(
                identifier.source_id,
                identifier.request_id,
                str(identifier.entity_type),
                stored_at=str(existing.get("updated_at")),
                attempted_at=str(updated_at),
            ) from cause

    def _is_duplicate_key_operation_failure(self, exc: OperationFailure) -> bool:
        return exc.code == 1 and "duplicate key" in str(exc)

    def _build_insert_doc(
        self,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        created_at: datetime,
    ) -> dict[str, Any]:
        """Build the update document for the insert path (no updated_at in $set).

        On first insert, ``updated_at`` is intentionally omitted so it stays
        absent (None) in the stored document, per R1. ``$setOnInsert`` ensures
        these immutable fields are only written on genuine inserts.

        Args:
            identifier: Entity mention triad (immutable once inserted).
            current: Initial cluster assignment.
            candidates: Pre-ordered candidate list.
            created_at: Insert timestamp — used as created_at; updated_at stays None.

        Returns:
            A MongoDB update document with ``$setOnInsert`` only.
        """
        return {
            "$setOnInsert": {
                "created_at": created_at,
                "about_entity_mention": identifier.model_dump(),
                "current_placement": current.model_dump(),
                "candidates": [c.model_dump() for c in candidates],
            },
        }

    def _build_update_doc(
        self,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
    ) -> dict[str, Any]:
        """Build the update document for the update path (sets updated_at in $set).

        On placement change, ``updated_at`` is set to the incoming timestamp.
        ``about_entity_mention`` is written in ``$set`` to ensure it is present
        on all docs (defensive against legacy missing-field docs).

        Args:
            identifier: Entity mention triad.
            current: New cluster assignment.
            candidates: Pre-ordered candidate list.
            updated_at: Incoming timestamp — bumped on every genuine placement change.

        Returns:
            A MongoDB update document with ``$set`` operator.
        """
        return {
            "$set": {
                "about_entity_mention": identifier.model_dump(),
                "current_placement": current.model_dump(),
                "candidates": [c.model_dump() for c in candidates],
                "updated_at": updated_at,
            },
        }

    async def _execute_insert(
        self,
        triad_hash: str,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
    ) -> dict[str, Any] | None:
        """Execute the insert path: ``find_one_and_update(upsert=True, filter={_id})``.

        ``updated_at`` is intentionally absent from the written document (R1).
        On concurrent insert race a ``DuplicateKeyError`` is converted to
        ``StaleOutcomeError`` against the winner's document.

        Args:
            triad_hash: The ``_id`` for this decision.
            identifier: Entity mention triad (used for error messages).
            current: Initial cluster assignment.
            candidates: Pre-ordered candidate list.
            updated_at: Timestamp written as ``created_at``; NOT stored as ``updated_at``.

        Returns:
            The stored document dict, or None if the write did not match.

        Raises:
            StaleOutcomeError: On concurrent insert race (DuplicateKeyError).
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB operation error.
        """
        update_doc = self._build_insert_doc(identifier, current, candidates, updated_at)
        try:
            return await self._collection.find_one_and_update(
                filter={"_id": triad_hash},
                update=update_doc,
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            await self._fetch_existing_and_raise_stale(triad_hash, identifier, updated_at, exc)
            raise RepositoryOperationError(str(exc)) from exc
        except OperationFailure as exc:
            if self._is_duplicate_key_operation_failure(exc):
                await self._fetch_existing_and_raise_stale(triad_hash, identifier, updated_at, exc)
            raise RepositoryOperationError(str(exc)) from exc
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc

    async def _execute_update(
        self,
        triad_hash: str,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
    ) -> dict[str, Any] | None:
        """Execute the update path: ``find_one_and_update(upsert=False, filter=R2)``.

        The R2 stale filter is a flat two-branch ``$or`` disjunction:
        - ``updated_at < incoming`` (already-updated record, incoming is fresh)
        - ``updated_at is None/absent AND created_at < incoming`` (never-updated)

        DocumentDB compatible: no nested ``$and``/``$or``, no ``$exists: false``.

        Args:
            triad_hash: The ``_id`` for this decision.
            identifier: Entity mention triad (used for error messages).
            current: New cluster assignment.
            candidates: Pre-ordered candidate list.
            updated_at: Incoming timestamp — written as ``updated_at`` on match.

        Returns:
            The updated document dict, or None if the stale filter rejected the write.

        Raises:
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB operation error.
        """
        stale_filter = {
            "_id": triad_hash,
            "$or": [
                {"updated_at": {"$lt": updated_at}},
                {"updated_at": None, "created_at": {"$lt": updated_at}},
            ],
        }
        update_doc = self._build_update_doc(identifier, current, candidates, updated_at)
        try:
            return await self._collection.find_one_and_update(
                filter=stale_filter,
                update=update_doc,
                upsert=False,
                return_document=pymongo.ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            await self._fetch_existing_and_raise_stale(triad_hash, identifier, updated_at, exc)
            raise RepositoryOperationError(str(exc)) from exc
        except OperationFailure as exc:
            if self._is_duplicate_key_operation_failure(exc):
                await self._fetch_existing_and_raise_stale(triad_hash, identifier, updated_at, exc)
            raise RepositoryOperationError(str(exc)) from exc
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc

    async def upsert_decision(
        self,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
        existing: Decision | None = None,
    ) -> Decision:
        """Atomically store or replace a decision, rejecting stale updates.

        Behaviour:

        - If no document exists for the triad → **insert path**
          (``_execute_insert``): ``find_one_and_update(upsert=True)`` with a
          simple ``_id`` filter and ``$setOnInsert``. ``updated_at`` stays
          absent on the stored document (R1). Concurrent insert races are
          caught and surfaced as ``StaleOutcomeError``.

        - If a document already exists → **update path** (``_execute_update``):
          ``find_one_and_update(upsert=False)`` with the R2 stale filter.
          ``updated_at`` is written in ``$set``.

        The optional ``existing`` parameter is a fast-path hint for callers
        that already hold the current document (e.g.
        ``DecisionStoreService.store_decision`` after its same-placement
        short-circuit pre-read). When ``existing`` is ``None`` the repository
        performs the pre-read itself, so direct callers (integration tests,
        future services) get correct behaviour without needing to know about
        the optimization. Either way the choice between insert/update path is
        based on actual database state, not on the caller's bookkeeping.

        Args:
            identifier: Entity mention triad identifying this decision.
            current: The new cluster assignment.
            candidates: Pre-ordered candidate list (callers must truncate to max).
            updated_at: Timestamp — must be strictly greater than stored updated_at
                when stored updated_at is non-null.
            existing: Optional fast-path hint. When provided, the repository
                trusts it and skips its own pre-read. When ``None``, the
                repository pre-reads internally (one extra round-trip).

        Returns:
            The persisted ``Decision`` after a successful write.

        Raises:
            StaleOutcomeError: If the stored ``updated_at`` >= incoming ``updated_at``.
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB error.
        """
        triad_hash = derive_provisional_cluster_id(identifier)

        if existing is None:
            try:
                existing_doc = await self._collection.find_one({"_id": triad_hash})
            except ConnectionFailure as exc:
                raise RepositoryConnectionError(str(exc)) from exc
            doc_present = existing_doc is not None
        else:
            doc_present = True

        if not doc_present:
            result = await self._execute_insert(
                triad_hash, identifier, current, candidates, updated_at
            )
        else:
            result = await self._execute_update(
                triad_hash, identifier, current, candidates, updated_at
            )

        if result is None:
            await self._fetch_existing_and_raise_stale(triad_hash, identifier, updated_at)
            raise RepositoryOperationError(
                "Upsert returned no document and no existing record found"
            )

        return self._from_document(result)

    async def find_by_triad(self, identifier: EntityMentionIdentifier) -> Decision | None:
        """Find a decision by its entity mention triad.

        Since ``Decision.id = triad_hash``, this is a direct ``_id`` lookup.

        Args:
            identifier: The entity mention triad to look up.

        Returns:
            The matching ``Decision``, or ``None`` if not found.
        """
        triad_hash = derive_provisional_cluster_id(identifier)
        return await self.find_by_id(triad_hash)

    async def find_with_filters(
        self,
        filters: DecisionFilters | None = None,
        cursor_params: CursorParams | None = None,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> CursorPage[Decision]:
        """Cursor-paginated query over decisions with optional filtering.

        Supports both:
        1. Curation use case: filters applied, custom ordering, mention ID matching
        2. Decision Store bulk sync use case: no filters, fixed (updated_at ASC, _id ASC)

        When ``filters`` is None, performs unfiltered traversal in Decision Store mode.

        Args:
            filters: Optional filter criteria. None for unfiltered traversal.
            cursor_params: Pagination params (cursor, limit). If None, uses default limit.
            mention_identifiers: When provided, restricts results to decisions whose
                ``about_entity_mention`` is in this list.

        Returns:
            A ``CursorPage`` containing results and an optional ``next_cursor``.
        """
        if cursor_params is None:
            cursor_params = CursorParams()

        count = 0

        # Unfiltered bulk sync mode (Decision Store)
        if filters is None:
            query: dict[str, Any] = {}
            sort_field = _FIELD_UPDATED_AT
            ascending = True
            sort = [(_FIELD_UPDATED_AT, 1), ("_id", 1)]
        else:
            # Filtered curation mode
            query = self._build_query(filters)

            if mention_identifiers is not None:
                id_docs = [
                    {
                        "source_id": mi.source_id,
                        "request_id": mi.request_id,
                        "entity_type": mi.entity_type,
                    }
                    for mi in mention_identifiers
                ]
                query[_FIELD_ABOUT_ENTITY_MENTION] = {"$in": id_docs}

            count = await self._collection.count_documents(query)

            sort_field, ascending = self._get_sort_info(filters.ordering)
            sort = self._build_sort(filters.ordering)

        # Apply cursor condition (same logic for both modes)
        if cursor_params.cursor is not None:
            raw_value, last_id = decode_cursor(cursor_params.cursor)
            sort_value = self._parse_cursor_sort_value(raw_value, sort_field)
            cursor_condition = self._build_cursor_condition(
                sort_field, sort_value, last_id, ascending
            )
            query = {"$and": [query, cursor_condition]} if query else cursor_condition

        # Fetch page_size + 1 to detect if there are more results
        fetch_limit = cursor_params.limit + 1
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        results = [self._from_document(doc) async for doc in cursor]

        # Encode next cursor if there are more results
        next_cursor = None
        if len(results) > cursor_params.limit:
            results = results[: cursor_params.limit]
            last = results[-1]
            sort_value = (
                self._extract_sort_value(last, sort_field)
                if filters is not None
                else last.updated_at
            )
            next_cursor = encode_cursor(sort_value, last.id)

        return CursorPage(results=results, count=count, next_cursor=next_cursor)

    async def find_delta_for_source(
        self,
        source_id: str,
        updated_since: datetime | None,
        cursor_params: CursorParams | None = None,
    ) -> CursorPage[Decision]:
        """Return decisions for a source changed after updated_since, cursor-paginated.

        Cold-start (updated_since=None) returns only decisions where updated_at is
        non-null (i.e., placement has moved at least once). Warm path uses $gt: T.

        Args:
            source_id: Filter to this source system.
            updated_since: Return decisions with updated_at > this value, or non-null
                decisions only if None (cold-start).
            cursor_params: Pagination parameters (cursor, limit).

        Returns:
            A CursorPage with matching decisions and an optional next_cursor.
        """
        if cursor_params is None:
            cursor_params = CursorParams()

        query: dict[str, Any] = {_FIELD_SOURCE_ID: source_id}
        if updated_since is not None:
            query[_FIELD_UPDATED_AT] = {"$gt": updated_since}
        else:
            # Cold-start: only return decisions that have moved at least once.
            # The insert path omits ``updated_at`` entirely (R1), so ``$exists: true``
            # alone is sufficient — it matches exactly the decisions in the
            # ``idx_decision_store_delta`` partial index, letting any reasonable
            # planner (MongoDB / FerretDB / DocumentDB) use that index.
            query[_FIELD_UPDATED_AT] = {"$exists": True}
            trace.get_current_span().set_attribute("decision_store.cold_start", True)

        sort_field = _FIELD_UPDATED_AT
        sort = [(_FIELD_UPDATED_AT, 1), ("_id", 1)]

        if cursor_params.cursor is not None:
            raw_value, last_id = decode_cursor(cursor_params.cursor)
            sort_value = self._parse_cursor_sort_value(raw_value, sort_field)
            cursor_condition = self._build_cursor_condition(
                sort_field, sort_value, last_id, True
            )
            query = {"$and": [query, cursor_condition]}

        fetch_limit = cursor_params.limit + 1
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        results = [self._from_document(doc) async for doc in cursor]

        next_cursor = None
        if len(results) > cursor_params.limit:
            results = results[: cursor_params.limit]
            last = results[-1]
            next_cursor = encode_cursor(last.updated_at, last.id)

        return CursorPage(results=results, next_cursor=next_cursor)

    async def find_mention_ids_by_cluster(
        self,
        cluster_id: str,
        limit: int,
    ) -> list[EntityMentionIdentifier]:
        cursor = self._collection.find(
            {_FIELD_CLUSTER_ID: cluster_id},
            projection={_FIELD_ABOUT_ENTITY_MENTION: 1, "_id": 0},
        )
        cursor = cursor.limit(limit)
        return [
            EntityMentionIdentifier.model_validate(doc[_FIELD_ABOUT_ENTITY_MENTION])
            async for doc in cursor
        ]

    async def count_distinct_clusters(self) -> int:
        result = await self._collection.distinct("current_placement.cluster_id")
        return len(result)

    async def average_cluster_size(self) -> float:
        pipeline: list[dict[str, Any]] = [
            {
                "$group": {
                    "_id": "$current_placement.cluster_id",
                    "count": {"$sum": 1},
                }
            },
            {"$group": {"_id": None, "avg": {"$avg": "$count"}}},
        ]
        cursor = await self._collection.aggregate(pipeline)
        result = await cursor.to_list()
        return result[0]["avg"] if result else 0.0

    async def ensure_indexes(self) -> None:
        """Create required MongoDB indexes for the decisions collection.

        Idempotent — safe to call on every startup. Creates:

        - ``idx_decision_store_updated_at_id``: ``(updated_at ASC, _id ASC)`` —
          supports the bulk-sync ``find_with_filters(filters=None)`` cursor pagination.
        - ``idx_decision_store_delta``: ``(source_id ASC, updated_at ASC, _id ASC)``
          with ``partialFilterExpression: {updated_at: {$exists: true}}`` —
          supports the refresh-bulk ``find_delta_for_source`` source-scoped delta
          scan (R7). MongoDB does not allow ``$ne`` in partial filters, but the
          insert path omits ``updated_at`` entirely (see ``upsert_decision``),
          so ``$exists: true`` selects exactly the same documents that can match
          a refresh-bulk query.
        """
        await self._collection.create_index(
            [(_FIELD_UPDATED_AT, pymongo.ASCENDING), ("_id", pymongo.ASCENDING)],
            name="idx_decision_store_updated_at_id",
            background=True,
        )
        await self._collection.create_index(
            [
                (_FIELD_SOURCE_ID, pymongo.ASCENDING),
                (_FIELD_UPDATED_AT, pymongo.ASCENDING),
                ("_id", pymongo.ASCENDING),
            ],
            name="idx_decision_store_delta",
            partialFilterExpression={"updated_at": {"$exists": True}},
            background=True,
        )
