from abc import abstractmethod
from dataclasses import dataclass
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
_FIELD_REVIEWED_SINCE_PLACEMENT = "reviewed_since_placement"
# Derived field added by the cluster-size aggregation pipeline branch.
# Not stored on decision documents; computed via $lookup + $addFields.
_FIELD_CLUSTER_SIZE = "cluster_size"


@dataclass(frozen=True, slots=True)
class ReviewMetadata:
    """Denormalised review-state primitives read off a decision document.

    Both fields are materialised on the ``decisions`` document by the
    integrator (placement reset) and the curation user-action service
    (``record_review``). Read together in a single projection by
    ``find_review_metadata`` so the curation list endpoint can build
    ``DecisionSummary`` rows without a second collection read.

    Attributes:
        previous_review_count: Lifetime count of curator actions ever
            recorded against the decision. Defaults to 0 for missing
            documents or absent field.
        reviewed_since_placement: ``True`` iff a curator action exists
            whose ``created_at`` is strictly after the decision's current
            placement boundary. Defaults to ``False`` for missing documents
            or absent field.
    """

    previous_review_count: int = 0
    reviewed_since_placement: bool = False


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
            reviewed_since_placement: When True/False, filter on the stored
                boolean materialised by the integrator (reset on placement
                advance) and ``record_review`` (conditionally set on curator
                action). None disables the filter. The two flags are
                orthogonal: combine ``ever_reviewed=True`` with
                ``reviewed_since_placement=False`` to select decisions that
                need re-visiting after an ERE update.
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
    async def record_review(self, decision_id: str, action_created_at: datetime) -> bool:
        """Atomically claim a curator-action slot for the current placement.

        Single ``update_one`` against the decision row, gated on
        ``reviewed_since_placement`` not already being ``True``. The write
        atomically (in one MongoDB operation):

        - Increments ``previous_review_count`` — the curator action happened
          and the counter ticks once per claimed slot.
        - Sets ``reviewed_since_placement`` to ``True`` when
          ``action_created_at`` is strictly greater than the stored placement
          boundary (``updated_at`` if non-null, else ``created_at``). When the
          action predates the current placement (delayed/out-of-order
          delivery), the flag is preserved at its current value via ``$cond``
          — stale actions never regress an already-reset flag.

        The filter ``reviewed_since_placement != True`` is the **concurrency
        guard**: it matches documents whose flag is ``false``, ``null``, or
        absent. The first concurrent caller to win the conditional update
        flips the flag and gets ``True``; every other concurrent caller sees
        ``modified_count == 0`` and gets ``False``. Callers MUST treat a
        ``False`` return as "this placement is already curated" and react
        accordingly (typically: roll back the just-saved ``user_action`` row
        and raise ``AlreadyCuratedError``). This closes the TOCTOU race that
        a separate read-then-write idempotency check could not.

        A missing document also returns ``False`` (``modified_count == 0``).
        The action save is the canonical write — the materialised primitives
        on the decision row are a denormalised mirror — so a missing decision
        leaves the database untouched.

        Args:
            decision_id: The ``_id`` of the decision document to update.
            action_created_at: The ``created_at`` of the user action being
                recorded. Compared against the stored placement boundary to
                decide whether to flip ``reviewed_since_placement``.

        Returns:
            ``True`` iff the slot was claimed (document matched and was
            updated). ``False`` iff another concurrent caller already claimed
            this placement's slot, or the decision does not exist.
        """

    @abstractmethod
    async def find_review_metadata(self, decision_ids: list[str]) -> dict[str, ReviewMetadata]:
        """Return ``(previous_review_count, reviewed_since_placement)`` for the IDs.

        Used by the curation service to attach review state to ``DecisionSummary``
        rows in a single round-trip — both primitives live on the decision row
        as stored fields. Missing documents or absent fields default to
        ``ReviewMetadata(0, False)`` — the same semantics as the per-document
        defaults documented on ``DecisionSummary``.

        Args:
            decision_ids: List of decision ``_id`` values to look up.

        Returns:
            Mapping of ``{decision_id: ReviewMetadata}``. IDs absent from the
            collection are omitted (callers default missing keys to
            ``ReviewMetadata(count=0, reviewed_since_placement=False)``).
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
        """Strip derived/denormalised fields before ``Decision`` validation.

        The ``Decision`` domain model forbids extra fields, but decision documents
        (or aggregation outputs) may carry adapter-only fields that are surfaced
        through other channels:

        - ``previous_review_count`` — a denormalised counter written by
          ``record_review`` and read via ``find_review_metadata``;
        - ``reviewed_since_placement`` — a denormalised boolean materialised by
          the integrator (reset on placement advance) and ``record_review``
          (conditionally set on curator action), read via ``find_review_metadata``;
        - ``cluster_size`` — a value derived by the cluster-size ordering
          aggregation (``$lookup`` on ``cluster_sizes``).

        Stripping all three here is the single funnel for every read path, so
        callers never hand a polluted document to ``model_validate``.
        """
        doc.pop(_FIELD_PREVIOUS_REVIEW_COUNT, None)
        doc.pop(_FIELD_REVIEWED_SINCE_PLACEMENT, None)
        doc.pop(_FIELD_CLUSTER_SIZE, None)
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

        The denormalised ``reviewed_since_placement`` flag is initialised to
        ``False`` here — a brand-new decision has no curator action against the
        current placement. The counter is left out so the curator-side writer
        owns its lifecycle exclusively.

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
                _FIELD_REVIEWED_SINCE_PLACEMENT: False,
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

        ``reviewed_since_placement`` is reset to ``False`` in the same ``$set``:
        every material placement advance invalidates whatever curator state was
        attached to the previous placement, and resetting in the same atomic
        write keeps the denormalised flag synchronous with ``updated_at``.

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
                _FIELD_REVIEWED_SINCE_PLACEMENT: False,
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

    async def record_review(self, decision_id: str, action_created_at: datetime) -> bool:
        """Atomically claim a curator-action slot for the current placement.

        Two classic-operator ``update_one`` writes (no aggregation-update
        pipeline — Amazon DocumentDB 5.0 does not support the pipeline form).
        Both filters require ``reviewed_since_placement != True``, the
        concurrency guard that serialises the claim at the database level.

        1. **Fresh path.** When ``action_created_at`` is strictly after the
           stored placement boundary (``updated_at`` if non-null, else
           ``created_at``), the first write increments
           ``previous_review_count`` and sets ``reviewed_since_placement =
           True`` — consuming the slot. The boundary comparison is encoded in
           the filter as the same flat ``$or`` used by ``_execute_update``.
        2. **Fallback path.** When the first write matches nothing, a second
           write (guarded only by ``$ne: True``) increments the counter without
           setting the flag. This covers a **stale** action (predates the
           boundary — delayed/out-of-order delivery): it is still counted and
           returns ``True``, but does **not** consume the slot, so a later fresh
           action can still flip the flag. When the flag is already ``True``
           (lost race) or the document is absent, this write also matches
           nothing.

        On a lost race or missing document, both writes report
        ``modified_count == 0`` and the method returns ``False``. Callers MUST
        treat ``False`` as "this placement is already curated" — typically by
        rolling back the just-saved ``user_action`` row and raising
        ``AlreadyCuratedError`` at the service layer.

        The guard ``{"$ne": True}`` matches ``false``, ``null``, and absent
        values — covering legacy documents that pre-date the materialisation
        of ``reviewed_since_placement``. No upsert is performed; the action
        save in ``user_actions`` is the canonical write, and the materialised
        primitives on the decision row are a denormalised mirror.

        Args:
            decision_id: The ``_id`` of the decision document to update.
            action_created_at: ``UserAction.created_at`` of the action being
                recorded. Compared against the stored placement boundary in the
                fresh-path filter.

        Returns:
            ``True`` iff the slot was claimed or the action was counted (either
            write matched). ``False`` iff another concurrent caller already
            claimed this placement's slot, or the decision document does not
            exist.
        """
        # Fresh path: the action is strictly after the placement boundary
        # (``updated_at`` if present, else ``created_at``). The comparison is
        # encoded in the filter as the same flat ``$or`` used by
        # ``_execute_update`` — classic operators only, DocumentDB-safe.
        fresh = await self._collection.update_one(
            {
                "_id": decision_id,
                _FIELD_REVIEWED_SINCE_PLACEMENT: {"$ne": True},
                "$or": [
                    {_FIELD_UPDATED_AT: {"$lt": action_created_at}},
                    {
                        _FIELD_UPDATED_AT: None,
                        _FIELD_CREATED_AT: {"$lt": action_created_at},
                    },
                ],
            },
            {
                "$inc": {_FIELD_PREVIOUS_REVIEW_COUNT: 1},
                "$set": {_FIELD_REVIEWED_SINCE_PLACEMENT: True},
            },
        )
        if fresh.modified_count > 0:
            return True

        # Fallback path: either the action is stale (predates the boundary) or
        # the flag is already True (lost race / absent document). The guard
        # ``$ne: True`` distinguishes them — a stale action is still counted
        # (counter incremented) without consuming the slot (flag not set); a lost race
        # matches nothing.
        stale = await self._collection.update_one(
            {
                "_id": decision_id,
                _FIELD_REVIEWED_SINCE_PLACEMENT: {"$ne": True},
            },
            {"$inc": {_FIELD_PREVIOUS_REVIEW_COUNT: 1}},
        )
        return stale.modified_count > 0

    async def find_review_metadata(self, decision_ids: list[str]) -> dict[str, ReviewMetadata]:
        """Return materialised review state for the given decision IDs.

        Fetches only ``_id``, ``previous_review_count`` and
        ``reviewed_since_placement`` in a single ``find`` query — both fields
        are stored on the decision row, no cross-collection join needed.

        Documents where a field is absent default to the field's documented
        zero value (``0`` for the counter, ``False`` for the flag).

        Args:
            decision_ids: List of decision ``_id`` values to look up.

        Returns:
            Mapping of ``{decision_id: ReviewMetadata}`` for all found documents.
        """
        if not decision_ids:
            return {}

        cursor = self._collection.find(
            {"_id": {"$in": decision_ids}},
            projection={
                _FIELD_PREVIOUS_REVIEW_COUNT: 1,
                _FIELD_REVIEWED_SINCE_PLACEMENT: 1,
            },
        )
        result: dict[str, ReviewMetadata] = {}
        async for doc in cursor:
            result[doc["_id"]] = ReviewMetadata(
                previous_review_count=doc.get(_FIELD_PREVIOUS_REVIEW_COUNT, 0),
                reviewed_since_placement=doc.get(_FIELD_REVIEWED_SINCE_PLACEMENT, False),
            )
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
        Both review primitives (``ever_reviewed``, ``reviewed_since_placement``) are
        plain ``$match`` predicates on stored fields — the previous correlated
        ``$lookup`` against ``user_actions`` is gone. The bulk-sync path
        (``filters=None``) ignores both flags.

        Args:
            filters: Optional filter criteria. None for unfiltered traversal.
            cursor_params: Pagination params (cursor, limit). If None, uses default limit.
            mention_identifiers: When provided, restricts results to decisions whose
                ``about_entity_mention`` is in this list.
            ever_reviewed: When True/False, filter on whether any curator action has
                ever been recorded (``previous_review_count > 0``). None disables it.
            reviewed_since_placement: When True/False, filter on the stored boolean
                materialised by the integrator + ``record_review``. None disables it.

        Returns:
            A ``CursorPage`` containing results and an optional ``next_cursor``.
            ``count`` is the exact match count for every combination of stored-field
            filters (field filters, ``mention_identifiers``, ``ever_reviewed``, and
            ``reviewed_since_placement``). The previous A3 upper-bound caveat no
            longer applies — all filters now run as ``$match`` on stored fields.
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
            self._augment_query_with_curation_filters(
                query,
                mention_identifiers=mention_identifiers,
                ever_reviewed=ever_reviewed,
                reviewed_since_placement=reviewed_since_placement,
            )
            count = await self._collection.count_documents(query)

            sort_field, ascending = self._get_sort_info(filters.ordering)
            sort = self._build_sort(filters.ordering)

        # --- Execution path selection ---
        # Cluster-size orderings require aggregation because the sort field is
        # derived via $lookup + $addFields and is not stored on the decision doc.
        # Every other filter — including ``reviewed_since_placement`` — runs as
        # a plain ``$match`` on a stored field and uses the simple ``find()`` path.
        # ``last_sort_raw_value`` captures the cluster_size integer for cursor
        # encoding when the aggregation path is active; it stays None for all
        # other paths.
        is_cluster_size_ordering = (
            filters is not None and filters.ordering in self._AGGREGATION_ORDERINGS
        )

        query, cursor_condition = self._apply_cursor_condition(
            query=query,
            cursor=cursor_params.cursor,
            sort_field=sort_field,
            ascending=ascending,
            is_cluster_size_ordering=is_cluster_size_ordering,
        )

        # Fetch page_size + 1 to detect if there are more results
        fetch_limit = cursor_params.limit + 1

        results, last_sort_raw_value = await self._fetch_page(
            query=query,
            sort=sort,
            fetch_limit=fetch_limit,
            is_cluster_size_ordering=is_cluster_size_ordering,
            cursor_condition=cursor_condition,
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

    @staticmethod
    def _augment_query_with_curation_filters(
        query: dict[str, Any],
        *,
        mention_identifiers: list[EntityMentionIdentifier] | None,
        ever_reviewed: bool | None,
        reviewed_since_placement: bool | None,
    ) -> None:
        """Add the curation-specific predicates to the stage-1 ``$match`` query.

        Mutates ``query`` in place. All three predicates are stored-field
        ``$match`` clauses, so each is index-eligible. Predicates with engine-
        portability constraints (``$in`` instead of ``$not``) follow the same
        rules as documented on the abstract method.
        """
        if mention_identifiers is not None:
            query[_FIELD_ABOUT_ENTITY_MENTION] = {
                "$in": [
                    {
                        "source_id": mi.source_id,
                        "request_id": mi.request_id,
                        "entity_type": mi.entity_type,
                    }
                    for mi in mention_identifiers
                ]
            }

        if ever_reviewed is not None:
            # ``$in: [0, None]`` treats a missing/null counter as never-reviewed
            # and avoids ``$not`` for DocumentDB / FerretDB portability.
            query[_FIELD_PREVIOUS_REVIEW_COUNT] = (
                {"$gt": 0} if ever_reviewed else {"$in": [0, None]}
            )

        if reviewed_since_placement is not None:
            # Stored boolean — ``False`` matches both ``false`` and absent
            # (legacy/un-backfilled) values via ``$in`` for the same
            # cross-engine reason as the counter.
            query[_FIELD_REVIEWED_SINCE_PLACEMENT] = (
                True if reviewed_since_placement else {"$in": [False, None]}
            )

    def _apply_cursor_condition(
        self,
        *,
        query: dict[str, Any],
        cursor: str | None,
        sort_field: str,
        ascending: bool,
        is_cluster_size_ordering: bool,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Decide where the keyset cursor predicate is applied.

        - Plain ``find()`` path: cursor predicate is on a *stored* field, so it
          merges into ``query`` and runs in stage 1 (indexable). Returns
          ``(merged_query, None)``.
        - Cluster-size aggregation path: cursor predicate is on the *derived*
          ``cluster_size`` field, which only exists after ``$addFields``. It must
          be deferred to a downstream ``$match`` (resolves C1). Returns
          ``(original_query, cursor_condition)``.

        When no cursor is supplied, ``cursor_condition`` is ``None`` and ``query``
        is unchanged.

        Args:
            query: The stage-1 match expression assembled from filters/flags.
            cursor: The opaque cursor string (or ``None`` for the first page).
            sort_field: The MongoDB field name driving the sort order.
            ascending: Sort direction; used to build the keyset predicate.
            is_cluster_size_ordering: True when the active sort key is the
                derived ``cluster_size`` field.

        Returns:
            ``(query, cursor_condition)``. ``cursor_condition`` is non-None only
            for the cluster-size aggregation path; callers forward it to
            ``_fetch_with_cluster_size_sort``.
        """
        if cursor is None:
            return query, None

        raw_value, last_id = decode_cursor(cursor)
        sort_value = self._parse_cursor_sort_value(raw_value, sort_field)
        cursor_condition = self._build_cursor_condition(sort_field, sort_value, last_id, ascending)
        if is_cluster_size_ordering:
            return query, cursor_condition
        merged = {"$and": [query, cursor_condition]} if query else cursor_condition
        return merged, None

    async def _fetch_page(
        self,
        *,
        query: dict[str, Any],
        sort: list[tuple[str, int]],
        fetch_limit: int,
        is_cluster_size_ordering: bool,
        cursor_condition: dict[str, Any] | None = None,
    ) -> tuple[list[Decision], Any]:
        """Select and run the read path; return ``(results, last_sort_raw_value)``.

        ``last_sort_raw_value`` is the derived ``cluster_size`` of the final row
        for cluster-size orderings (used to encode the next cursor), else None.
        Every other path uses a plain ``find()`` — the previous review-filter
        aggregation is gone now that ``reviewed_since_placement`` is a stored,
        indexable field.

        ``cursor_condition`` is forwarded only on the cluster-size aggregation
        path; the plain-find path has already merged its cursor condition into
        ``query``.
        """
        if is_cluster_size_ordering:
            return await self._fetch_with_cluster_size_sort(
                query=query,
                sort=sort,
                fetch_limit=fetch_limit,
                cursor_condition=cursor_condition,
            )
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        return [self._from_document(doc) async for doc in cursor], None

    async def _fetch_with_cluster_size_sort(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]],
        fetch_limit: int,
        cursor_condition: dict[str, Any] | None = None,
    ) -> tuple[list[Decision], int | None]:
        """Execute an aggregation pipeline that joins cluster_sizes and sorts by cluster size.

        The pipeline:

        1. ``$match``      — apply the pre-built filter query (indexes apply here).
                              This contains only stored-field predicates; the
                              cursor predicate on the derived ``cluster_size``
                              is **never** placed here (resolves C1).
        2. ``$lookup``     — join ``cluster_sizes`` on ``current_placement.cluster_id == _id``.
        3. ``$addFields``  — derive ``cluster_size`` as the first element of the joined
                              array, defaulting to 0 for decisions whose cluster has no
                              size record.
        4. ``$project``    — remove the ``_cluster_meta`` helper array.
        5. ``$match``      — (conditional) apply the cursor predicate on the now-materialised
                              ``cluster_size`` field. Present iff a cursor was supplied.
        6. ``$sort``       — sort by ``cluster_size`` (±1) with ``_id`` tiebreaker.
        7. ``$limit``      — limit to ``fetch_limit`` documents.

        Limiting after (not before) the cursor ``$match`` is essential: limiting
        first would let the cursor filter under-fill the page.

        ``reviewed_since_placement`` filtering is **not** added here — when the
        filter is active it lives in the stage-1 ``$match`` via the stored field,
        same as every other filter.

        The raw document still contains ``cluster_size`` after the pipeline so that
        ``_from_document`` receives a clean decision doc after stripping it.

        Args:
            query: Pre-built MongoDB match expression covering stored-field
                predicates only (filters, mention_identifiers, ever_reviewed,
                reviewed_since_placement).
            sort: Sort specification — should be ``[(cluster_size, ±1), (_id, ±1)]``.
            fetch_limit: Number of documents to fetch (page size + 1).
            cursor_condition: Optional keyset cursor predicate on the derived
                ``cluster_size`` field. Inserted as a post-``$addFields`` ``$match``
                when non-None.

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

        if cursor_condition is not None:
            # cluster_size only exists from $addFields onwards; the cursor
            # predicate references it, so it must run here — never in stage 1.
            pipeline.append({"$match": cursor_condition})

        pipeline += [
            {"$sort": sort_stage},
            {"$limit": fetch_limit},
        ]

        raw_docs: list[dict[str, Any]] = []
        agg_cursor = await self._collection.aggregate(pipeline)
        async for doc in agg_cursor:
            raw_docs.append(doc)

        # Capture the derived cluster_size for cursor encoding *before* the
        # documents are converted (``_from_document`` strips derived fields).
        last_cluster_size: int | None = raw_docs[-1].get(_FIELD_CLUSTER_SIZE) if raw_docs else None

        decisions = [self._from_document(doc) for doc in raw_docs]
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
            cursor_condition = self._build_cursor_condition(sort_field, sort_value, last_id, True)
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
