import hashlib
import json
from datetime import UTC, datetime

from erspec.models.core import (
    CanonicalEntityIdentifier,
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
    UserAction,
    UserActionType,
)
from polyfactory.factories.pydantic_factory import ModelFactory

from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.users.domain.users import User


def _escape_turtle_string(value: str) -> str:
    if not value:
        return value
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


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

    # TODO: rename field to identified_by in erspec
    @classmethod
    def identifiedBy(cls) -> EntityMentionIdentifier:  # noqa: N802
        return EntityMentionIdentifierFactory.build()

    @classmethod
    def content_type(cls) -> str:
        return "application/ld+json"

    @classmethod
    def content(cls) -> str:
        return json.dumps(cls._payload())

    @classmethod
    def _organisation_payload(cls) -> dict:
        faker = cls.__faker__
        return {
            "legal_name": faker.company(),
            "country_code": faker.country_code(),
            "nuts_code": faker.lexify("??", letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            + faker.numerify("###"),
            "post_code": faker.postcode(),
            "post_name": faker.city(),
            "thoroughfare": faker.street_address(),
        }

    @classmethod
    def _procedure_payload(cls) -> dict:
        faker = cls.__faker__
        return {
            "identifier": faker.numerify("##_####"),
            "title": faker.job() + " services",
            "description": faker.paragraph(nb_sentences=3),
            "legal_basis": faker.numerify("3####L####"),
            "procedure_type": faker.random_element(
                [
                    "open",
                    "restricted",
                    "neg-wo-call",
                    "neg-w-call",
                    "competitive-dialogue",
                ]
            ),
            "purpose_nature": faker.random_element(["services", "works", "supplies"]),
            "purpose_classification": faker.numerify("########"),
        }

    @classmethod
    def _payload_for(cls, entity_type: str) -> dict:
        if entity_type == "PROCEDURE":
            return cls._procedure_payload()
        return cls._organisation_payload()

    @classmethod
    def _payload(cls) -> dict:
        return cls._organisation_payload()

    @classmethod
    def parsed_representation(cls) -> str:
        return json.dumps(cls._payload())


class ResolutionRequestRecordFactory(EntityMentionFactory):
    __model__ = ResolutionRequestRecord

    @classmethod
    def content_hash(cls) -> str:
        return hashlib.sha256(cls.__faker__.uuid4().encode()).hexdigest()

    @classmethod
    def received_at(cls) -> datetime:
        return datetime.now(UTC)

    @classmethod
    def _organisation_turtle(cls, payload: dict) -> str:
        legal_name = _escape_turtle_string(payload["legal_name"])
        country_code = _escape_turtle_string(payload["country_code"])
        address_props = [f'epo:hasCountryCode "{country_code}"']
        if nuts_code := payload.get("nuts_code"):
            address_props.append(
                f'epo:hasNutsCode "{_escape_turtle_string(nuts_code)}"'
            )
        if post_code := payload.get("post_code"):
            address_props.append(f'locn:postCode "{_escape_turtle_string(post_code)}"')
        if post_name := payload.get("post_name"):
            address_props.append(f'locn:postName "{_escape_turtle_string(post_name)}"')
        if thoroughfare := payload.get("thoroughfare"):
            address_props.append(
                f'locn:thoroughfare "{_escape_turtle_string(thoroughfare)}"'
            )
        address_content = " ;\n        ".join(address_props)
        uid = cls.__faker__.uuid4()
        return (
            "@prefix org: <http://www.w3.org/ns/org#> .\n"
            "@prefix cccev: <http://data.europa.eu/m8g/> .\n"
            "@prefix epo: <http://data.europa.eu/a4g/ontology#> .\n"
            "@prefix locn: <http://www.w3.org/ns/locn#> .\n"
            "@prefix epd: <http://data.europa.eu/a4g/resource/> .\n\n"
            f"epd:ent{uid} a org:Organization ;\n"
            f'    epo:hasLegalName "{legal_name}" ;\n'
            f"    cccev:registeredAddress [\n"
            f"        {address_content}\n"
            f"    ] .\n"
        )

    @classmethod
    def _procedure_turtle(cls, payload: dict) -> str:
        uid = cls.__faker__.uuid4()
        identifier = _escape_turtle_string(payload["identifier"])
        title = _escape_turtle_string(payload["title"])
        description = _escape_turtle_string(payload["description"])
        legal_basis = _escape_turtle_string(payload["legal_basis"])
        procedure_type = _escape_turtle_string(payload["procedure_type"])
        purpose_nature = _escape_turtle_string(payload["purpose_nature"])
        purpose_classification = _escape_turtle_string(
            payload["purpose_classification"]
        )
        legal_basis_uri = f"http://publications.europa.eu/resource/authority/legal-basis/{legal_basis}"
        procedure_type_uri = (
            "http://publications.europa.eu/resource/authority/"
            f"procurement-procedure-type/{procedure_type}"
        )
        nature_uri = f"http://publications.europa.eu/resource/authority/contract-nature/{purpose_nature}"
        cpv_uri = f"http://data.europa.eu/cpv/cpv/{purpose_classification}"
        return (
            "@prefix epo: <http://data.europa.eu/a4g/ontology#> .\n"
            "@prefix epd: <http://data.europa.eu/a4g/resource/> .\n"
            "@prefix dct: <http://purl.org/dc/terms/> .\n\n"
            f"epd:ent{uid} a epo:Procedure ;\n"
            f'    dct:title "{title}" ;\n'
            f'    dct:description "{description}" ;\n'
            f"    epo:hasID [\n"
            f'        epo:hasIdentifierValue "{identifier}"\n'
            f"    ] ;\n"
            f"    epo:hasLegalBasis <{legal_basis_uri}> ;\n"
            f"    epo:hasProcedureType <{procedure_type_uri}> ;\n"
            f"    epo:hasPurpose [\n"
            f"        epo:hasContractNatureType <{nature_uri}> ;\n"
            f"        epo:hasMainClassification <{cpv_uri}>\n"
            f"    ] .\n"
        )

    @classmethod
    def build_for_entity_type(
        cls, entity_type: str, **kwargs
    ) -> ResolutionRequestRecord:
        payload = cls._payload_for(entity_type)
        if entity_type == "PROCEDURE":
            turtle_content = cls._procedure_turtle(payload)
        else:
            turtle_content = cls._organisation_turtle(payload)
        content_hash = hashlib.sha256(turtle_content.encode()).hexdigest()
        identifier = kwargs.pop(
            "identifiedBy", None
        ) or EntityMentionIdentifierFactory.build(entity_type=entity_type)
        return cls.build(
            identifiedBy=identifier,
            content=turtle_content,
            content_type="text/turtle",
            parsed_representation=json.dumps(payload),
            content_hash=content_hash,
            **kwargs,
        )


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
        return datetime.now(UTC)

    @classmethod
    def updated_at(cls) -> datetime:
        return datetime.now(UTC)


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
        return datetime.now(UTC)

    @classmethod
    def metadata(cls) -> None:
        return None


class UserFactory(ModelFactory):
    __model__ = User

    @classmethod
    def id(cls) -> str:
        return f"user-{cls.__faker__.uuid4()[:8]}"

    @classmethod
    def email(cls) -> str:
        return cls.__faker__.email()

    @classmethod
    def hashed_password(cls) -> str:
        return "$argon2id$v=19$m=65536,t=3,p=4$fakehash"

    @classmethod
    def is_active(cls) -> bool:
        return True

    @classmethod
    def is_superuser(cls) -> bool:
        return False

    @classmethod
    def is_verified(cls) -> bool:
        return False

    @classmethod
    def created_at(cls) -> datetime:
        return datetime.now(UTC)

    @classmethod
    def updated_at(cls) -> None:
        return None
