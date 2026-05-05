import re
from abc import abstractmethod

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
    ResolutionRequestRepository,
)

# Minimum number of characters required to trigger a substring regex search.
# Queries shorter than this threshold would cause a full-collection scan because
# a 1- or 2-character regex pattern matches too broadly to be filtered by a
# range index. Three characters is the practical minimum for useful results.
MIN_SEARCH_LENGTH = 3


class EntityMentionCurationRepository(ResolutionRequestRepository):
    """Repository for entity mention retrieval in curation.

    Extends ``ResolutionRequestRepository`` with batch-fetch and substring
    search capabilities needed by curation services.
    """

    @abstractmethod
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        """Batch-fetch entity mentions by their identifiers."""

    @abstractmethod
    async def search_identifiers(
        self,
        text: str,
    ) -> list[EntityMentionIdentifier]:
        """Substring-search entity mentions and return matching identifiers."""


class MongoEntityMentionCurationRepository(
    EntityMentionCurationRepository, MongoResolutionRequestRepository
):
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        triad_ids = [self._triad_id(i) for i in identifiers]
        cursor = self._collection.find({"_id": {"$in": triad_ids}})
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._from_document(doc) async for doc in cursor]

    async def search_identifiers(
        self,
        text: str,
    ) -> list[EntityMentionIdentifier]:
        """Case-insensitive substring search across content + parsed_representation.

        Uses ``$regex`` with ``$or`` rather than MongoDB's ``$text`` operator so
        the same query runs unchanged on MongoDB, FerretDB, and Amazon
        DocumentDB. DocumentDB does not support text indexes or the ``$text``
        operator at all; ``$regex`` is the cross-engine portable choice.

        Queries shorter than ``MIN_SEARCH_LENGTH`` (3 characters) are rejected
        with an empty result without touching the database. A 1- or 2-character
        regex pattern matches the overwhelming majority of documents and would
        cause a full-collection scan with no practical utility.

        Trade-off: ``$regex`` does not provide linguistic stemming, scoring, or
        result ranking — it returns documents whose ``content`` or
        ``parsed_representation`` contains the literal substring (escaped
        before regex compilation to avoid metacharacter injection).

        Args:
            text: The substring to search for. Must be at least ``MIN_SEARCH_LENGTH``
                characters; shorter inputs (including empty string) return ``[]``
                without querying the database.

        Returns:
            A list of ``EntityMentionIdentifier`` objects for matching documents,
            or an empty list when the query is too short or produces no results.
        """
        if not text or len(text) < MIN_SEARCH_LENGTH:
            return []
        pattern = re.escape(text)
        cursor = self._collection.find(
            {
                "$or": [
                    {"content": {"$regex": pattern, "$options": "i"}},
                    {"parsed_representation": {"$regex": pattern, "$options": "i"}},
                ]
            },
            projection={"identifiedBy": 1, "_id": 0},
        )
        return [EntityMentionIdentifier.model_validate(doc["identifiedBy"]) async for doc in cursor]
