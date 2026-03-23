from datetime import datetime
from typing import Any

from erspec.models.core import Decision

from ers.commons.adapters.repository import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)


class DecisionRepository(
    AsyncReadRepository[Decision, str],
    AsyncWriteRepository[Decision, str],
):
    """Repository for decision projection persistence and querying."""


class MongoDecisionRepository(
    BaseMongoRepository[Decision, str],
    DecisionRepository,
):
    _model_class = Decision
    _id_field = "id"
    _collection_name = "decisions"

    _DATETIME_FIELDS: set[str] = {"created_at", "updated_at"}

    def _build_cursor_condition(
        self,
        sort_field: str,
        sort_value: Any,
        last_id: str,
        ascending: bool,
    ) -> dict[str, Any]:
        """Build MongoDB $or filter for cursor-based seek.

        Args:
            sort_field: The MongoDB field name used for primary sort ordering.
            sort_value: The sort field value from the last seen document, or None.
            last_id: The _id of the last seen document (tie-breaker).
            ascending: True for ascending order, False for descending.

        Returns:
            A MongoDB query fragment that seeks past the last seen position.
        """
        id_op = "$gt" if ascending else "$lt"
        val_op = "$gt" if ascending else "$lt"

        if sort_value is None:
            if ascending:
                return {
                    "$or": [
                        {sort_field: None, "_id": {id_op: last_id}},
                        {sort_field: {"$ne": None}},
                    ]
                }
            return {sort_field: None, "_id": {id_op: last_id}}

        return {
            "$or": [
                {sort_field: {val_op: sort_value}},
                {sort_field: sort_value, "_id": {id_op: last_id}},
            ]
        }

    def _parse_cursor_sort_value(self, value: Any, sort_field: str) -> Any:
        """Reconstruct typed value from cursor payload.

        Converts ISO 8601 strings back to datetime objects for datetime sort fields.

        Args:
            value: Raw value decoded from the opaque cursor.
            sort_field: The MongoDB field name used for sorting.

        Returns:
            The value cast to its correct Python type for use in a MongoDB query.
        """
        if value is None:
            return None
        if sort_field in self._DATETIME_FIELDS:
            return datetime.fromisoformat(value)
        return value
