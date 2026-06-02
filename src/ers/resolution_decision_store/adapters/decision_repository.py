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
_FIELD_PREVIOUS_REVIEW_COUNT = "previous_review_count"
_COLLECTION_USER_ACTIONS = "user_actions"
# Derived field added by the cluster-size aggregation pipeline branch.
# Not stored on decision documents; computed via $lookup + $addFields.
_FIELD_CLUSTER_SIZE = "cluster_size"


class DecisionRepository(BaseDecisionRepository):
    """Repository for decision projection persistence and curation specific querying."""

    @abstractmethod
    async def find_with_filters(
        self,
        filters: DecisionFilters | None = None,
        cursor_params: CursorParams | None = None,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
        *,
        ever_reviewed: bool | None = None,
        reviewed_since_placement: bool | None = None,
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
            ever_reviewed: When True, return only decisions with at least one
                recorded curator action (``previous_review_count > 0``); when
                False, only decisions never reviewed. None disables the filter.
            reviewed_since_placement: When True, return only decisions where a
                user_action exists with ``created_at`` after the decision's
                current placement timestamp (``updated_at`` or ``created_at``);
                when False, only decisions with no such action. None disables
                the filter. The two flags are orthogonal: combine
                ``ever_reviewed=True`` with ``reviewed_since_placement=False`` to
                select decisions that need re-visiting after an ERE update.
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

    @abstractmethod
    async def increment_review_count(self, decision_id: str) -> None:
        """Atomically increment the previous_review_count field on the given decision.

        No-op if the document is missing — the action save is the canonical write,
        the counter is a denormalised mirror (see spec §3.1 R8).

        Args:
            decision_id: The ``_id`` of the decision document to increment.
        """

    @abstractmethod
    async def find_review_counts(self, decision_ids: list[str]) -> dict[str, int]:
        """Return previous_review_count values for the given decision IDs.

        Used by the curation service to attach counts to ``DecisionSummary`` rows
        without changing the ``find_with_filters`` signature (which is shared with
        the Decision Store sync path).  Missing documents or documents without the
        field are treated as 0.

        Args:
            decision_ids: List of decision ``_id`` values to look up.

        Returns:
            Mapping of ``{decision_id: count}``.  IDs absent from the collection
            are omitted (callers should default-to-0 on missing keys).
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
        DecisionOrdering.CLUSTER_SIZE_ASC: (_FIELD_CLUSTER_SIZE, True),
        DecisionOrdering.CLUSTER_SIZE_DESC: (_FIELD_CLUSTER_SIZE, False),
    }

    # Orderings that require an aggregation pipeline because the sort field is
    # derived (not stored on the decision document itself).
    _AGGREGATION_ORDERINGS: frozenset[DecisionOrdering] = frozenset(
        {DecisionOrdering.CLUSTER_SIZE_ASC, DecisionOrdering.CLUSTER_SIZE_DESC}
    )

    def _from_document(self, doc: dict[str, Any]) -> Decision:
        """Strip the denormalised ``previous_review_count`` before validation.

        ``previous_review_count`` is a denormalised counter stored on the decision
        document (written by ``increment_review_count``), but the ``Decision``
        domain model forbids extra fields. It is read separately via
        ``find_review_counts`` and must not reach ``model_validate`` here.
        """
        doc.pop(_FIELD_PREVIOUS_REVIEW_COUNT, None)
        return super()._from_document(doc)

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
        """Return the sort key value from a Decision domain object.

        Args:
            decision: The decision to inspect.
            sort_field: MongoDB field name used as the primary sort key.

        Returns:
            The field value, or ``None`` for unknown or derived fields.
            Derived fields (e.g. ``cluster_size``) cannot be extracted from the
            domain object — callers that need those values must capture them
            directly from the raw aggregation document before conversion.
        """
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

    async def increment_review_count(self, decision_id: str) -> None:
        """Atomically increment the previous_review_count field on the given decision.

        Uses ``$inc`` so the field is initialised from zero on the first call even
        when the field is absent from legacy documents.  No upsert is performed —
        a missing document is silently ignored (the action save is the canonical
        write; this counter is a denormalised mirror).

        Args:
            decision_id: The ``_id`` of the decision document to increment.
        """
        await self._collection.update_one(
            {"_id": decision_id},
            {"$inc": {"previous_review_count": 1}},
        )

    async def find_review_counts(self, decision_ids: list[str]) -> dict[str, int]:
        """Return previous_review_count values for the given decision IDs.

        Fetches only the ``_id`` and ``previous_review_count`` fields in a single
        ``find`` query.  Documents where the field is absent are treated as 0.

        Args:
            decision_ids: List of decision ``_id`` values to look up.

        Returns:
            Mapping of ``{decision_id: count}`` for all found documents.
        """
        if not decision_ids:
            return {}

        cursor = self._collection.find(
            {"_id": {"$in": decision_ids}},
            projection={"previous_review_count": 1},
        )
        result: dict[str, int] = {}
        async for doc in cursor:
            result[doc["_id"]] = doc.get("previous_review_count", 0)
        return result

    async def find_with_filters(
        self,
        filters: DecisionFilters | None = None,
        cursor_params: CursorParams | None = None,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
        *,
        ever_reviewed: bool | None = None,
        reviewed_since_placement: bool | None = None,
    ) -> CursorPage[Decision]:
        """Cursor-paginated query over decisions with optional filtering.

        Supports both:
        1. Curation use case: filters applied, custom ordering, mention ID matching
        2. Decision Store bulk sync use case: no filters, fixed (updated_at ASC, _id ASC)

        When ``filters`` is None, performs unfiltered traversal in Decision Store mode.
        ``ever_reviewed`` is a plain ``$match`` on the stored ``previous_review_count``.
        When ``reviewed_since_placement`` is not None, the curation path switches to an
        aggregation that ``$lookup``s ``user_actions`` and applies the review-state
        predicate *before* sort/limit (so pagination never under-fills).  The bulk-sync
        path (``filters=None``) ignores both flags.

        Args:
            filters: Optional filter criteria. None for unfiltered traversal.
            cursor_params: Pagination params (cursor, limit). If None, uses default limit.
            mention_identifiers: When provided, restricts results to decisions whose
                ``about_entity_mention`` is in this list.
            ever_reviewed: When True/False, filter on whether any curator action has
                ever been recorded (``previous_review_count > 0``). None disables it.
            reviewed_since_placement: When True/False, filter on whether a user_action
                exists since the current placement. None disables it.

        Returns:
            A ``CursorPage`` containing results and an optional ``next_cursor``.
            ``count`` reflects only the stored-field query (field filters,
            ``mention_identifiers``, and ``ever_reviewed``); it does **not** account
            for the ``reviewed_since_placement`` lookup filter, which is applied
            inside the aggregation after the count is taken (A3). When
            ``reviewed_since_placement`` is set, treat ``count`` as an upper bound on
            the filtered total, not an exact count.
        """
        if cursor_params is None:
            cursor_params = CursorParams()

        count = 0

        # Unfiltered bulk sync mode (Decision Store) — review flags are ignored here.
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

            if ever_reviewed is not None:
                # ``$in: [0, None]`` treats a missing/null counter as never-reviewed
                # and avoids ``$not`` for DocumentDB / FerretDB portability.
                query[_FIELD_PREVIOUS_REVIEW_COUNT] = (
                    {"$gt": 0} if ever_reviewed else {"$in": [0, None]}
                )

            # NOTE (A3): counts the stored-field query only. The
            # ``reviewed_since_placement`` lookup filter is applied later in the
            # aggregation, so this count is an upper bound when that filter is set.
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

        # --- Execution path selection ---
        # Cluster-size orderings require aggregation because the sort field is
        # derived via $lookup + $addFields and is not stored on the decision doc.
        # ``last_sort_raw_value`` captures the cluster_size integer for cursor
        # encoding when that path is active; it stays None for all other paths.
        is_cluster_size_ordering = (
            filters is not None
            and filters.ordering in self._AGGREGATION_ORDERINGS
        )
        results, last_sort_raw_value = await self._fetch_page(
            query=query,
            sort=sort,
            fetch_limit=fetch_limit,
            filters=filters,
            reviewed_since_placement=reviewed_since_placement,
            is_cluster_size_ordering=is_cluster_size_ordering,
        )

        # Encode next cursor if there are more results
        next_cursor = None
        if len(results) > cursor_params.limit:
            results = results[: cursor_params.limit]
            last = results[-1]
            if is_cluster_size_ordering:
                # Use the raw cluster_size captured from the aggregation document.
                sort_value = last_sort_raw_value
            elif filters is not None:
                sort_value = self._extract_sort_value(last, sort_field)
            else:
                sort_value = last.updated_at
            next_cursor = encode_cursor(sort_value, last.id)

        return CursorPage(results=results, count=count, next_cursor=next_cursor)

    async def _fetch_page(
        self,
        *,
        query: dict[str, Any],
        sort: list[tuple[str, int]],
        fetch_limit: int,
        filters: DecisionFilters | None,
        reviewed_since_placement: bool | None,
        is_cluster_size_ordering: bool,
    ) -> tuple[list[Decision], Any]:
        """Select and run the read path; return ``(results, last_sort_raw_value)``.

        ``last_sort_raw_value`` is the derived ``cluster_size`` of the final row
        for cluster-size orderings (used to encode the next cursor), else None.
        """
        if is_cluster_size_ordering:
            return await self._fetch_with_cluster_size_sort(
                query=query,
                sort=sort,
                fetch_limit=fetch_limit,
                reviewed=reviewed_since_placement,
            )
        if reviewed_since_placement is not None and filters is not None:
            results = await self._fetch_with_review_filter(
                query=query,
                sort=sort,
                fetch_limit=fetch_limit,
                reviewed=reviewed_since_placement,
            )
            return results, None
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        return [self._from_document(doc) async for doc in cursor], None

    async def _fetch_with_review_filter(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]],
        fetch_limit: int,
        reviewed: bool,
    ) -> list[Decision]:
        """Execute an aggregation pipeline that joins user_actions to filter by review state.

        A decision is considered *reviewed* when there exists at least one user_action
        whose ``about_entity_mention`` triad matches the decision's triad and whose
        ``created_at`` is strictly after the decision's current-placement timestamp
        (``updated_at`` if non-null, else ``created_at``).

        The pipeline filters **before** limiting, so a page never under-fills:

        1. ``$match`` — apply the pre-built filter query (same predicates as ``find()``).
        2. ``$lookup`` — correlated sub-pipeline against ``user_actions`` joining on
           the embedded ``about_entity_mention`` triad and the temporal predicate.
        3. ``$match`` — keep only documents where ``_has_recent_action`` is non-empty
           (``reviewed=True``) or empty (``reviewed=False``).
        4. ``$sort`` — apply the requested ordering so cursor pagination is stable.
        5. ``$limit`` — limit to ``fetch_limit`` after the review filter.
        6. ``$project`` — remove the temporary ``_has_recent_action`` array so that
           ``_from_document`` receives clean decision documents.

        Limiting after (not before) the review ``$match`` is essential: limiting
        first would let the review filter drop most of a fetched page, returning a
        short page and prematurely ending pagination.

        Args:
            query: Pre-built MongoDB match expression (may include cursor condition).
            sort: Sort specification as a list of ``(field, direction)`` pairs.
            fetch_limit: Number of documents to fetch (page size + 1).
            reviewed: True to keep reviewed decisions; False to keep pending ones.

        Returns:
            List of ``Decision`` domain objects.
        """
        sort_stage = {field: direction for field, direction in sort}

        review_match: dict[str, Any] = (
            {"_has_recent_action": {"$ne": []}}
            if reviewed
            else {"_has_recent_action": {"$eq": []}}
        )

        pipeline: list[dict[str, Any]] = [
            {"$match": query if query else {}},
            self._recent_action_lookup_stage(),
            {"$match": review_match},
            {"$sort": sort_stage},
            {"$limit": fetch_limit},
            {"$project": {"_has_recent_action": 0}},
        ]

        agg_cursor = await self._collection.aggregate(pipeline)
        return [self._from_document(doc) async for doc in agg_cursor]

    @staticmethod
    def _recent_action_lookup_stage() -> dict[str, Any]:
        """Build the correlated ``$lookup`` that flags a user_action since placement.

        Adds ``_has_recent_action`` (non-empty iff such an action exists), joining
        ``user_actions`` on the embedded ``about_entity_mention`` triad and the
        temporal predicate ``created_at > (updated_at, else created_at)``.  Shared
        by the review filter and the cluster-size sort path.
        """
        return {
            "$lookup": {
                "from": _COLLECTION_USER_ACTIONS,
                "let": {
                    "triad": f"${_FIELD_ABOUT_ENTITY_MENTION}",
                    "since": {"$ifNull": [f"${_FIELD_UPDATED_AT}", f"${_FIELD_CREATED_AT}"]},
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": [f"${_FIELD_ABOUT_ENTITY_MENTION}", "$$triad"]},
                                    {"$gt": [f"${_FIELD_CREATED_AT}", "$$since"]},
                                ]
                            }
                        }
                    },
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "_has_recent_action",
            }
        }

    async def _fetch_with_cluster_size_sort(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]],
        fetch_limit: int,
        reviewed: bool | None,
    ) -> tuple[list[Decision], int | None]:
        """Execute an aggregation pipeline that joins cluster_sizes and sorts by cluster size.

        The pipeline:

        1. ``$match``     — apply the pre-built filter query (indexes apply here).
        2. ``$lookup``    — join ``cluster_sizes`` on ``current_placement.cluster_id == _id``.
        3. ``$addFields`` — derive ``cluster_size`` as the first element of the joined array,
                            defaulting to 0 for decisions whose cluster has no size record.
        4. ``$project``   — remove the ``_cluster_meta`` helper array.
        5. ``$lookup``    — (conditional) join ``user_actions`` when ``reviewed`` is not None.
        6. ``$match``     — (conditional) filter by review state.
        7. ``$project``   — (conditional) remove ``_has_recent_action``.
        8. ``$sort``      — sort by ``cluster_size`` (±1) with ``_id`` tiebreaker.
        9. ``$limit``     — limit to ``fetch_limit`` documents.

        The raw document still contains ``cluster_size`` after the pipeline so that
        ``_from_document`` receives a clean decision doc after stripping it.

        Args:
            query: Pre-built MongoDB match expression (may include cursor condition).
            sort: Sort specification — should be ``[(cluster_size, ±1), (_id, ±1)]``.
            fetch_limit: Number of documents to fetch (page size + 1).
            reviewed: When not None, adds the user_actions join and review-state
                match; True keeps reviewed decisions, False keeps pending ones.

        Returns:
            A tuple of ``(decisions, last_cluster_size)`` where ``last_cluster_size``
            is the ``cluster_size`` value of the final document returned (used as the
            cursor sort value for the next page), or ``None`` when the result is empty.
        """
        sort_stage = {field: direction for field, direction in sort}

        pipeline: list[dict[str, Any]] = [
            {"$match": query if query else {}},
            {
                "$lookup": {
                    "from": "cluster_sizes",
                    "localField": _FIELD_CLUSTER_ID,
                    "foreignField": "_id",
                    "as": "_cluster_meta",
                }
            },
            {
                "$addFields": {
                    _FIELD_CLUSTER_SIZE: {
                        "$ifNull": [{"$arrayElemAt": ["$_cluster_meta.size", 0]}, 0]
                    }
                }
            },
            {"$project": {"_cluster_meta": 0}},
        ]

        if reviewed is not None:
            review_match: dict[str, Any] = (
                {"_has_recent_action": {"$ne": []}}
                if reviewed
                else {"_has_recent_action": {"$eq": []}}
            )
            pipeline += [
                self._recent_action_lookup_stage(),
                {"$match": review_match},
                {"$project": {"_has_recent_action": 0}},
            ]

        pipeline += [
            {"$sort": sort_stage},
            {"$limit": fetch_limit},
        ]

        raw_docs: list[dict[str, Any]] = []
        agg_cursor = await self._collection.aggregate(pipeline)
        async for doc in agg_cursor:
            raw_docs.append(doc)

        last_cluster_size: int | None = raw_docs[-1].get(_FIELD_CLUSTER_SIZE) if raw_docs else None

        # Strip the derived cluster_size field before handing to _from_document.
        decisions = [self._from_document({k: v for k, v in doc.items() if k != _FIELD_CLUSTER_SIZE})
                     for doc in raw_docs]
        return decisions, last_cluster_size

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
