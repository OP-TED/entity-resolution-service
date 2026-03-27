"""Polyfactories producing mock Faker data for ERS REST API response schemas."""

from datetime import UTC, datetime

from polyfactory.factories.pydantic_factory import ModelFactory

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.lookup import (
    BulkLookupResponse,
    BulkLookupResult,
    LookupResponse,
    RefreshBulkResponse,
)
from ers.ers_rest_api.domain.resolution import (
    BulkResolveResponse,
    EntityMentionResolutionResult,
)
from tests.unit.factories import ClusterReferenceFactory, EntityMentionIdentifierFactory


class EntityMentionResolutionResultFactory(ModelFactory):
    __model__ = EntityMentionResolutionResult

    @classmethod
    def identified_by(cls):
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def canonical_entity_id(cls) -> str:
        return f"cluster-{cls.__faker__.uuid4()}"

    @classmethod
    def status(cls) -> ResolutionOutcome:
        return cls.__faker__.random_element(
            [ResolutionOutcome.CANONICAL, ResolutionOutcome.PROVISIONAL]
        )

    @classmethod
    def error(cls) -> None:
        return None


class BulkResolveResponseFactory(ModelFactory):
    __model__ = BulkResolveResponse

    @classmethod
    def results(cls) -> list[EntityMentionResolutionResult]:
        return EntityMentionResolutionResultFactory.batch(cls.__faker__.random_int(min=2, max=5))


class LookupResponseFactory(ModelFactory):
    __model__ = LookupResponse

    @classmethod
    def identified_by(cls):
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def cluster_reference(cls):
        return ClusterReferenceFactory.build()

    @classmethod
    def last_updated(cls) -> datetime:
        return cls.__faker__.date_time_between(start_date="-30d", end_date="now", tzinfo=UTC)


class BulkLookupResultFactory(ModelFactory):
    __model__ = BulkLookupResult

    @classmethod
    def identified_by(cls):
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def cluster_reference(cls):
        return ClusterReferenceFactory.build()

    @classmethod
    def last_updated(cls) -> datetime:
        return cls.__faker__.date_time_between(start_date="-30d", end_date="now", tzinfo=UTC)

    @classmethod
    def error(cls) -> None:
        return None


class BulkLookupResponseFactory(ModelFactory):
    __model__ = BulkLookupResponse

    @classmethod
    def results(cls) -> list[BulkLookupResult]:
        return BulkLookupResultFactory.batch(cls.__faker__.random_int(min=2, max=5))


class RefreshBulkResponseFactory(ModelFactory):
    __model__ = RefreshBulkResponse

    @classmethod
    def deltas(cls) -> list[LookupResponse]:
        return LookupResponseFactory.batch(cls.__faker__.random_int(min=1, max=5))

    @classmethod
    def has_more(cls) -> bool:
        return False

    @classmethod
    def continuation_cursor(cls) -> None:
        return None
