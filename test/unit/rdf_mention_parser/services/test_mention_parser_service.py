"""Unit tests for MentionParserService and build_sparql_query.

Covers TC-008 through TC-013 from the EPIC.
Adapter is mocked; domain logic is tested in isolation.
"""

from unittest.mock import MagicMock, patch

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier
from rdflib import Graph

from ers import (
    config as ers_config,
)  # aliased: 'config' fixture name conflicts in this module
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError,
    EmptyExtractionError,
    EntityTypeMismatchError,
    MalformedRDFError,
    MultipleEntitiesFoundError,
    UnsupportedContentTypeError,
    UnsupportedEntityTypeError,
)
from ers.rdf_mention_parser.domain.rdf_mapping_config import (
    EntityTypeConfig,
    RDFMappingConfig,
)
from ers.rdf_mention_parser.services.mention_parser_service import (
    MentionParserService,
    build_sparql_query,
    load_config,
    parse_entity_mention,
)

# ---------------------------------------------------------------------------
# Shared config fixture
# ---------------------------------------------------------------------------

_NAMESPACES = {
    "org": "http://www.w3.org/ns/org#",
    "epo": "http://data.europa.eu/a4g/ontology#",
    "cccev": "http://data.europa.eu/m8g/",
    "locn": "http://www.w3.org/ns/locn#",
}

_ORG_FIELDS = {
    "legal_name": "epo:hasLegalName",
    "country_code": "cccev:registeredAddress/epo:hasCountryCode",
    "nuts_code": "cccev:registeredAddress/epo:hasNutsCode",
    "post_code": "cccev:registeredAddress/locn:postCode",
    "post_name": "cccev:registeredAddress/locn:postName",
    "thoroughfare": "cccev:registeredAddress/locn:thoroughfare",
}

_ORG_KEY = "ORGANISATION"


def _make_entity_mention(
    content: str, content_type: str = "text/turtle", entity_type: str = _ORG_KEY
) -> EntityMention:
    return EntityMention(
        identifiedBy=EntityMentionIdentifier(
            source_id="test-source",
            request_id="test-request-001",
            entity_type=entity_type,
        ),
        content=content,
        content_type=content_type,
    )


@pytest.fixture
def config() -> RDFMappingConfig:
    return RDFMappingConfig(
        namespaces=_NAMESPACES,
        entity_types={
            "ORGANISATION": {
                "rdf_type": "org:Organization",
                "display_name_field": "legal_name",
                "fields": dict(_ORG_FIELDS),
            }
        },
    )


@pytest.fixture
def adapter_mock():
    mock = MagicMock()
    mock.parse_to_graph.return_value = Graph()
    mock.has_entity_of_type.return_value = True
    mock.execute_sparql.return_value = [
        {
            "entity": "http://example.org/org/1",
            "legal_name": "Test Org",
            "country_code": "http://publications.europa.eu/resource/authority/country/DEU",
            "nuts_code": "http://data.europa.eu/nuts/code/DE1",
            "post_code": "10115",
            "post_name": "Berlin",
            "thoroughfare": "Unter den Linden 1",
        }
    ]
    return mock


@pytest.fixture
def service(config, adapter_mock) -> MentionParserService:
    return MentionParserService(config, adapter_mock)


# ---------------------------------------------------------------------------
# TC-008 — SPARQL query builder
# ---------------------------------------------------------------------------


class TestBuildSparqlQuery:
    def test_includes_all_prefix_declarations(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        for prefix in _NAMESPACES:
            assert f"PREFIX {prefix}:" in query

    def test_selects_entity_and_all_field_variables(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        assert "?entity" in query
        for field in _ORG_FIELDS:
            assert f"?{field}" in query

    def test_anchors_entity_with_rdf_type(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        assert "?entity a org:Organization" in query

    def test_wraps_each_field_in_optional(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        assert query.count("OPTIONAL") == len(_ORG_FIELDS)

    def test_uses_property_path_for_multi_hop_fields(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        assert "cccev:registeredAddress/epo:hasCountryCode" in query

    def test_has_no_limit_clause(self, config):
        query = build_sparql_query(config, config.entity_types["ORGANISATION"])
        assert "LIMIT" not in query

    def test_single_field_config_builds_valid_query(self, config):
        single_config = EntityTypeConfig(
            rdf_type="org:Organization",
            display_name_field="legal_name",
            fields={"legal_name": "epo:hasLegalName"},
        )
        query = build_sparql_query(config, single_config)
        assert "?legal_name" in query
        assert query.count("OPTIONAL") == 1


# ---------------------------------------------------------------------------
# TC-009, TC-011, TC-012, TC-013 — MentionParserService.parse (happy + error paths)
# ---------------------------------------------------------------------------


class TestMentionParserServiceParse:
    def test_returns_dict_with_all_six_fields(self, service, adapter_mock):
        result = service.parse(_make_entity_mention("dummy content"))

        assert isinstance(result, dict)
        assert len(result) == 6
        assert result["legal_name"] == "Test Org"
        assert result["post_code"] == "10115"

    def test_passes_content_and_type_to_adapter(self, service, adapter_mock):
        service.parse(_make_entity_mention("my content"))
        adapter_mock.parse_to_graph.assert_called_once_with("my content", "text/turtle")

    def test_partial_result_returned_when_some_fields_none(
        self, service, adapter_mock, config
    ):
        adapter_mock.execute_sparql.return_value = [
            {
                "entity": "http://example.org/org/1",
                "legal_name": "Test Org",
                "country_code": "DEU",
                "nuts_code": None,
                "post_code": None,
                "post_name": None,
                "thoroughfare": None,
            }
        ]
        result = service.parse(_make_entity_mention("dummy"))
        assert result["legal_name"] == "Test Org"
        assert result["nuts_code"] is None


# ---------------------------------------------------------------------------
# TC-010 — ContentTooLargeError
# ---------------------------------------------------------------------------


class TestContentTooLarge:
    def test_raises_at_one_byte_over_limit(self, service):
        oversized = "x" * (ers_config.ERS_PARSER_MAX_CONTENT_LENGTH + 1)
        with pytest.raises(ContentTooLargeError) as exc_info:
            service.parse(_make_entity_mention(oversized))
        assert exc_info.value.max_bytes == ers_config.ERS_PARSER_MAX_CONTENT_LENGTH

    def test_passes_at_exact_limit(self, service, adapter_mock):
        # Build a string whose UTF-8 encoding is exactly ers_config.ERS_PARSER_MAX_CONTENT_LENGTH bytes.
        padding = "x" * ers_config.ERS_PARSER_MAX_CONTENT_LENGTH
        # The adapter mock returns a valid result, so parse succeeds.
        result = service.parse(_make_entity_mention(padding))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TC-011 — EntityTypeMismatchError
# ---------------------------------------------------------------------------


class TestEntityTypeMismatch:
    def test_raises_when_graph_has_no_entity_of_declared_type(
        self, service, adapter_mock
    ):
        adapter_mock.has_entity_of_type.return_value = False

        with pytest.raises(EntityTypeMismatchError) as exc_info:
            service.parse(_make_entity_mention("turtle content"))
        assert _ORG_KEY in exc_info.value.message


# ---------------------------------------------------------------------------
# TC-014 — MultipleEntitiesFoundError
# ---------------------------------------------------------------------------


class TestMultipleEntitiesFound:
    def test_raises_when_multiple_distinct_entities_found(self, service, adapter_mock):
        adapter_mock.execute_sparql.return_value = [
            {
                "entity": "http://example.org/org/1",
                "legal_name": "Org A",
                "country_code": "DEU",
                "nuts_code": None,
                "post_code": None,
                "post_name": None,
                "thoroughfare": None,
            },
            {
                "entity": "http://example.org/org/2",
                "legal_name": "Org B",
                "country_code": "FRA",
                "nuts_code": None,
                "post_code": None,
                "post_name": None,
                "thoroughfare": None,
            },
        ]

        with pytest.raises(MultipleEntitiesFoundError) as exc_info:
            service.parse(_make_entity_mention("turtle content"))
        assert exc_info.value.count == 2

    def test_merges_rows_for_same_entity(self, service, adapter_mock):
        """Multi-valued OPTIONAL properties produce multiple rows for one entity.

        The service should merge them (first non-None wins) instead of raising.
        """
        adapter_mock.execute_sparql.return_value = [
            {
                "entity": "http://example.org/org/1",
                "legal_name": "Test Org",
                "country_code": "DEU",
                "nuts_code": None,
                "post_code": "10115",
                "post_name": None,
                "thoroughfare": None,
            },
            {
                "entity": "http://example.org/org/1",
                "legal_name": "Test Org",
                "country_code": None,
                "nuts_code": "DE1",
                "post_code": None,
                "post_name": "Berlin",
                "thoroughfare": None,
            },
        ]

        result = service.parse(_make_entity_mention("turtle content"))
        assert result["legal_name"] == "Test Org"
        assert result["country_code"] == "DEU"
        assert result["nuts_code"] == "DE1"
        assert result["post_name"] == "Berlin"


# ---------------------------------------------------------------------------
# TC-012 — EmptyExtractionError
# ---------------------------------------------------------------------------


class TestEmptyExtraction:
    def test_raises_when_all_fields_are_none(self, service, adapter_mock):
        adapter_mock.execute_sparql.return_value = [
            {
                "entity": "http://example.org/org/1",
                "legal_name": None,
                "country_code": None,
                "nuts_code": None,
                "post_code": None,
                "post_name": None,
                "thoroughfare": None,
            }
        ]

        with pytest.raises(EmptyExtractionError) as exc_info:
            service.parse(_make_entity_mention("turtle content"))
        assert _ORG_KEY in exc_info.value.message

    def test_raises_when_sparql_returns_no_rows(self, service, adapter_mock):
        adapter_mock.execute_sparql.return_value = []

        with pytest.raises(EmptyExtractionError):
            service.parse(_make_entity_mention("turtle content"))


# ---------------------------------------------------------------------------
# TC-013 — MalformedRDFError propagation
# ---------------------------------------------------------------------------


class TestMalformedRDF:
    def test_propagates_malformed_rdf_error_from_adapter(self, service, adapter_mock):
        adapter_mock.parse_to_graph.side_effect = MalformedRDFError("text/turtle")

        with pytest.raises(MalformedRDFError):
            service.parse(_make_entity_mention("bad turtle"))


# ---------------------------------------------------------------------------
# UnsupportedContentTypeError + UnsupportedEntityTypeError propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_propagates_unsupported_content_type(self, service, adapter_mock):
        adapter_mock.parse_to_graph.side_effect = UnsupportedContentTypeError(
            "application/json"
        )

        with pytest.raises(UnsupportedContentTypeError):
            service.parse(_make_entity_mention("{}", content_type="application/json"))

    def test_raises_unsupported_entity_type_for_unknown_key(self, service):
        with pytest.raises(UnsupportedEntityTypeError):
            service.parse(_make_entity_mention("content", entity_type="UNKNOWN_TYPE"))


# ---------------------------------------------------------------------------
# Public service API — load_config + parse_entity_mention
# ---------------------------------------------------------------------------

_SERVICE_MODULE = "ers.rdf_mention_parser.services.mention_parser_service"


class TestLoadConfig:
    def test_delegates_to_config_reader(self, config):
        with patch(
            f"{_SERVICE_MODULE}.RDFConfigReader.from_file", return_value=config
        ) as mock_reader:
            result = load_config()

        mock_reader.assert_called_once_with(ers_config.RDF_MENTION_CONFIG_FILE)
        assert result is config

    def test_propagates_file_not_found(self):
        with (
            patch(
                f"{_SERVICE_MODULE}.RDFConfigReader.from_file",
                side_effect=FileNotFoundError("missing"),
            ),
            pytest.raises(FileNotFoundError),
        ):
            load_config()


class TestParseEntityMention:
    def test_delegates_to_service(self, config):
        expected = {"legal_name": "Test Org", "country_code": "DEU"}
        entity_mention = _make_entity_mention("content")
        with (
            patch(f"{_SERVICE_MODULE}.RDFParserAdapter") as mock_adapter_cls,
            patch(f"{_SERVICE_MODULE}.MentionParserService") as mock_service_cls,
        ):
            mock_service_cls.return_value.parse.return_value = expected

            result = parse_entity_mention(entity_mention, config)

        mock_adapter_cls.assert_called_once_with()
        mock_service_cls.assert_called_once_with(config, mock_adapter_cls.return_value)
        mock_service_cls.return_value.parse.assert_called_once_with(entity_mention)
        assert result == expected

    def test_propagates_domain_errors(self, config):
        entity_mention = _make_entity_mention("content")
        with (
            patch(f"{_SERVICE_MODULE}.RDFParserAdapter"),
            patch(f"{_SERVICE_MODULE}.MentionParserService") as mock_service_cls,
        ):
            mock_service_cls.return_value.parse.side_effect = EntityTypeMismatchError(
                _ORG_KEY
            )

            with pytest.raises(EntityTypeMismatchError):
                parse_entity_mention(entity_mention, config)
