"""Curation-owned read of review-state derived from the user_actions log.

Computes the per-row ``reviewed_since_placement`` flag for a page of decisions by
reading the ``user_actions`` collection — which curation owns. Moving this
*flag-attachment* read out of the decision-store adapter (A1) restores the
single-owner-per-collection boundary of ADR-D1N / ADR-B2N for the projection path.

Scope note: the ``reviewed_since_placement`` *filter* (the ``$lookup`` joining
``user_actions`` inside the paginated decision aggregation) still lives in the
decision-store adapter, because it must run at the database level to keep keyset
pagination correct. That remaining cross-collection join is an intentional,
documented exception, not covered by this reader.
"""
from typing import Any, Protocol

from erspec.models.core import Decision
from pymongo.asynchronous.database import AsyncDatabase

_COLLECTION_USER_ACTIONS = "user_actions"
_FIELD_ABOUT_ENTITY_MENTION = "about_entity_mention"
_FIELD_CREATED_AT = "created_at"


class ReviewStateReader(Protocol):
    """Read port: attach review-state derived from the user action log."""

    async def reviewed_since_placement(self, decisions: list[Decision]) -> dict[str, bool]:
        """Return, per decision, whether a curator action exists since its placement.

        "Since the current placement" means a ``user_action`` whose ``created_at``
        is strictly after the decision's ``updated_at`` (or ``created_at`` when the
        decision was never re-placed).

        Args:
            decisions: The page of decisions to evaluate.

        Returns:
            ``{decision.id: bool}`` for every input decision (decisions with no
            recent action map to ``False``).
        """
        ...


class MongoReviewStateReader:
    """MongoDB implementation of :class:`ReviewStateReader`.

    Args:
        db: Connected async MongoDB database; the ``user_actions`` collection is
            resolved from it.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._user_actions = db[_COLLECTION_USER_ACTIONS]

    @staticmethod
    def _triad_key(mention: dict[str, Any]) -> tuple[Any, Any, Any]:
        """Stable identity key for an ``about_entity_mention`` subdocument."""
        return (
            mention.get("source_id"),
            mention.get("request_id"),
            mention.get("entity_type"),
        )

    async def reviewed_since_placement(self, decisions: list[Decision]) -> dict[str, bool]:
        """Return, per decision, whether a curator action exists since its placement.

        One indexed read over ``user_actions``: an ``$or`` of per-decision
        ``{about_entity_mention, created_at > since}`` clauses. The page is bounded
        by the page size, so the disjunction is small.

        Args:
            decisions: The page of decisions to evaluate.

        Returns:
            ``{decision.id: bool}`` for every input decision.
        """
        result: dict[str, bool] = {d.id: False for d in decisions}
        if not decisions:
            return result

        or_clauses: list[dict[str, Any]] = []
        key_to_id: dict[tuple[Any, Any, Any], str] = {}
        for decision in decisions:
            since = decision.updated_at or decision.created_at
            # Dump the triad once and use it for both the query clause and the
            # result key. Because the query matches the whole subdocument by
            # equality, any returned user_action's triad equals this exact dump,
            # so the keys map back deterministically (no serialization drift).
            triad = decision.about_entity_mention.model_dump(mode="python")
            or_clauses.append(
                {_FIELD_ABOUT_ENTITY_MENTION: triad, _FIELD_CREATED_AT: {"$gt": since}}
            )
            key_to_id[self._triad_key(triad)] = decision.id

        cursor = self._user_actions.find(
            {"$or": or_clauses},
            projection={_FIELD_ABOUT_ENTITY_MENTION: 1, "_id": 0},
        )
        async for doc in cursor:
            decision_id = key_to_id.get(self._triad_key(doc.get(_FIELD_ABOUT_ENTITY_MENTION, {})))
            if decision_id is not None:
                result[decision_id] = True
        return result
