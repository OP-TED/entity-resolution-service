"""MongoDB repository for the Resolution Decision Store.

``MongoDecisionStoreRepository`` is a parallel sibling to
``MongoDecisionCurationRepository``: both extend ``MongoDecisionRepository``
from ``ers.commons.adapters.decision_repository``, both operate on the
``decisions`` collection, and both use ``erspec.Decision`` as the domain model.
"""
from datetime import datetime
from typing import Any

import pymongo
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.commons.adapters.decision_repository import MongoDecisionRepository
from ers.commons.domain.cursor import decode_cursor, encode_cursor
from ers.commons.domain.exceptions import InvalidCursorError as CommonInvalidCursorError
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.adapters.provisional_id import derive_provisional_cluster_id
from ers.resolution_decision_store.domain.errors import (
    InvalidCursorError,
    RepositoryConnectionError,
    RepositoryOperationError,
    StaleOutcomeError,
)


class MongoDecisionStoreRepository(MongoDecisionRepository):
    """MongoDB-backed persistence for resolution decisions.

    Extends ``MongoDecisionRepository`` (which provides ``erspec.Decision``,
    ``decisions`` collection, ``_id_field='id'``). Adds atomic upsert with
    staleness detection, triad-based lookup, and cursor-paginated traversal.

    ``Decision.id`` equals the SHA-256 triad hash, set once via ``$setOnInsert``
    on first write and never changed.
    """

    async def upsert_decision(
        self,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
    ) -> Decision:
        """Atomically store or replace a decision, rejecting stale updates.

        Args:
            identifier: Entity mention triad identifying this decision.
            current: The new cluster assignment.
            candidates: Pre-ordered candidate list (callers must truncate to max).
            updated_at: Timestamp — must be strictly greater than stored updated_at.

        Returns:
            The persisted ``Decision`` after a successful write.

        Raises:
            StaleOutcomeError: If the stored ``updated_at`` >= incoming ``updated_at``.
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB error.
        """
        triad_hash = derive_provisional_cluster_id(identifier)
        update_doc = {
            "$set": {
                "about_entity_mention": identifier.model_dump(),
                "current_placement": current.model_dump(),
                "candidates": [c.model_dump() for c in candidates],
                "updated_at": updated_at,
            },
            "$setOnInsert": {
                "id": triad_hash,
                "created_at": updated_at,
            },
        }
        try:
            result = await self._collection.find_one_and_update(
                filter={"_id": triad_hash, "updated_at": {"$lt": updated_at}},
                update=update_doc,
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            # Concurrent upsert race: another writer inserted the same triad first.
            existing = await self._collection.find_one({"_id": triad_hash})
            if existing:
                raise StaleOutcomeError(
                    identifier.source_id,
                    identifier.request_id,
                    str(identifier.entity_type),
                    stored_at=str(existing.get("updated_at")),
                    attempted_at=str(updated_at),
                ) from exc
            raise RepositoryOperationError(str(exc)) from exc
        except OperationFailure as exc:
            raise RepositoryOperationError(str(exc)) from exc
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc

        if result is None:
            existing = await self._collection.find_one({"_id": triad_hash})
            if existing:
                raise StaleOutcomeError(
                    identifier.source_id,
                    identifier.request_id,
                    str(identifier.entity_type),
                    stored_at=str(existing.get("updated_at")),
                    attempted_at=str(updated_at),
                )
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

    async def query_paginated(
        self,
        cursor: str | None = None,
        page_size: int = 250,
    ) -> CursorPage[Decision]:
        """Cursor-paginated traversal over all stored decisions.

        Orders by ``(updated_at ASC, _id ASC)``. Designed for bulk operations
        (EPIC-07 Bulk Lookup, Spine-C sync).

        Args:
            cursor: Opaque pagination token from a previous response, or ``None``
                for the first page.
            page_size: Maximum number of results per page.

        Returns:
            A ``CursorPage`` containing results and an optional ``next_cursor``.

        Raises:
            InvalidCursorError: If the cursor string cannot be decoded.
            RepositoryConnectionError: On MongoDB connection failure.
        """
        query: dict[str, Any] = {}
        if cursor is not None:
            try:
                raw_value, last_id = decode_cursor(cursor)
            except CommonInvalidCursorError as exc:
                raise InvalidCursorError(str(exc)) from exc
            sort_value = self._parse_cursor_sort_value(raw_value, "updated_at")
            query = self._build_cursor_condition("updated_at", sort_value, last_id, ascending=True)

        sort = [("updated_at", pymongo.ASCENDING), ("_id", pymongo.ASCENDING)]
        fetch_count = page_size + 1
        try:
            raw_docs = (
                await self._collection.find(query).sort(sort).limit(fetch_count).to_list(fetch_count)
            )
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc

        has_next = len(raw_docs) > page_size
        page_docs = raw_docs[:page_size]

        # Encode cursor from raw docs before _from_document mutates _id → id.
        next_cursor: str | None = None
        if has_next and page_docs:
            last = page_docs[-1]
            next_cursor = encode_cursor(last["updated_at"], last["_id"])

        records = [self._from_document(doc) for doc in page_docs]

        return CursorPage(results=records, next_cursor=next_cursor)

    async def ensure_indexes(self) -> None:
        """Create required MongoDB indexes for the decisions collection.

        Idempotent — safe to call on every startup. Creates a compound index
        on ``(updated_at ASC, _id ASC)`` to support cursor pagination performance.
        """
        await self._collection.create_index(
            [("updated_at", pymongo.ASCENDING), ("_id", pymongo.ASCENDING)],
            name="idx_decision_store_updated_at_id",
            background=True,
        )
