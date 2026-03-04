import json
from datetime import datetime, timezone

from polyfactory.factories.pydantic_factory import ModelFactory

from erspec.models.core import (
    CanonicalEntityIdentifier,
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
    UserAction,
    UserActionType,
)


class EntityMentionIdentifierFactory(ModelFactory):
    __model__ = EntityMentionIdentifier

    @classmethod
    def source_id(cls) -> str:
        return f"source-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def request_id(cls) -> str:
        return f"request-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def entity_type(cls) -> str:
        return "ORGANISATION"


class ClusterReferenceFactory(ModelFactory):
    __model__ = ClusterReference

    @classmethod
    def cluster_id(cls) -> str:
        return f"cluster-{cls.__faker__.uuid4()}"

    @classmethod
    def confidence_score(cls) -> float:
        return round(cls.__faker__.pyfloat(min_value=0.0, max_value=1.0), 2)

    @classmethod
    def similarity_score(cls) -> float:
        return round(cls.__faker__.pyfloat(min_value=0.0, max_value=1.0), 2)


class EntityMentionFactory(ModelFactory):
    __model__ = EntityMention

    @classmethod
    def identifiedBy(cls) -> EntityMentionIdentifier:
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def content_type(cls) -> str:
        return "application/ld+json"

    @classmethod
    def content(cls) -> str:
        return '{"name": "Example Entity"}'

    @classmethod
    def _payload(cls) -> dict:
        faker = cls.__faker__

        return {
            "name": faker.company(),
            "registration_number": faker.bothify(text="??########"),
            "country": faker.country_code(),
            "city": faker.city(),
            "email": faker.company_email(),
        }

    @classmethod
    def parsed_representation(cls) -> str:
        return f"{json.dumps(cls._payload())}"


class CanonicalEntityIdentifierFactory(ModelFactory):
    __model__ = CanonicalEntityIdentifier

    @classmethod
    def identifier(cls) -> str:
        return f"canonical-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def equivalent_to(cls) -> list[EntityMentionIdentifier]:
        return EntityMentionIdentifierFactory.batch(3)


class DecisionFactory(ModelFactory):
    __model__ = Decision

    @classmethod
    def id(cls) -> str:
        return f"decision-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def about_entity_mention(cls) -> EntityMentionIdentifier:
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def current_placement(cls) -> ClusterReference:
        return ClusterReferenceFactory.build()

    @classmethod
    def candidates(cls) -> list[ClusterReference]:
        return ClusterReferenceFactory.batch(3)

    @classmethod
    def created_at(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def updated_at(cls) -> datetime:
        return datetime.now(timezone.utc)


class UserActionFactory(ModelFactory):
    __model__ = UserAction

    @classmethod
    def id(cls) -> str:
        return f"action-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def about_entity_mention(cls) -> EntityMentionIdentifier:
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def candidates(cls) -> list[ClusterReference]:
        return ClusterReferenceFactory.batch(3)

    @classmethod
    def selected_cluster(cls) -> ClusterReference:
        return ClusterReferenceFactory.build()

    @classmethod
    def action_type(cls) -> UserActionType:
        return UserActionType.ACCEPT_TOP

    @classmethod
    def actor(cls) -> str:
        return "curator-1"

    @classmethod
    def created_at(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def metadata(cls) -> None:
        return None
