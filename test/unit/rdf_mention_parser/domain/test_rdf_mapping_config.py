"""Unit tests for EntityTypeConfig and RDFMappingConfig domain models.

Covers EPIC TC-001, TC-002, TC-003.
"""

import pytest
from pydantic import ValidationError

from ers.rdf_mention_parser.domain.exceptions import UnsupportedEntityTypeError
from ers.rdf_mention_parser.domain.rdf_mapping_config import (
    EntityTypeConfig,
    RDFMappingConfig,
)

# ---------------------------------------------------------------------------
# Minimal valid fixtures
# ---------------------------------------------------------------------------

MINIMAL_NAMESPACES = {
    "org": "http://www.w3.org/ns/org#",
    "epo": "http://data.europa.eu/a4g/ontology#",
    "cccev": "http://data.europa.eu/m8g/",
    "locn": "http://www.w3.org/ns/locn#",
}

ORGANISATION_FIELDS = {
    "legal_name": "epo:hasLegalName",
    "country_code": "cccev:registeredAddress/epo:hasCountryCode",
    "nuts_code": "cccev:registeredAddress/epo:hasNutsCode",
    "post_code": "cccev:registeredAddress/locn:postCode",
    "post_name": "cccev:registeredAddress/locn:postName",
    "thoroughfare": "cccev:registeredAddress/locn:thoroughfare",
}


def minimal_config(extra_types: dict | None = None) -> dict:
    entity_types = {
        "ORGANISATION": {
            "rdf_type": "org:Organization",
            "entity_label_field": "legal_name",
            "fields": dict(ORGANISATION_FIELDS),
        }
    }
    if extra_types:
        entity_types.update(extra_types)
    return {"namespaces": dict(MINIMAL_NAMESPACES), "entity_types": entity_types}


# ---------------------------------------------------------------------------
# TC-001 — Load valid configuration
# ---------------------------------------------------------------------------


class TestRDFMappingConfigValid:
    def test_loads_single_entity_type_with_six_fields(self):
        config = RDFMappingConfig(**minimal_config())

        assert len(config.namespaces) == 4
        assert len(config.entity_types) == 1
        assert len(config.entity_types["ORGANISATION"].fields) == 6

    def test_loads_two_entity_types(self):
        extra = {
            "PROCEDURE": {
                "rdf_type": "epo:Procedure",
                "entity_label_field": "title",
                "fields": {"title": "epo:hasTitle"},
            }
        }
        config = RDFMappingConfig(**minimal_config(extra_types=extra))

        assert len(config.entity_types) == 2
        assert "ORGANISATION" in config.entity_types
        assert "PROCEDURE" in config.entity_types

    def test_field_names_and_paths_are_preserved(self):
        config = RDFMappingConfig(**minimal_config())
        fields = config.entity_types["ORGANISATION"].fields

        assert fields["legal_name"] == "epo:hasLegalName"
        assert fields["country_code"] == "cccev:registeredAddress/epo:hasCountryCode"

    def test_full_sample_config_loads(self, sample_rdf_mapping: str):
        """TC-001 with the canonical sample fixture (6 + 7 fields, 6 namespaces)."""
        import yaml

        data = yaml.safe_load(sample_rdf_mapping)
        config = RDFMappingConfig(**data)

        assert "ORGANISATION" in config.entity_types
        assert "PROCEDURE" in config.entity_types
        assert len(config.entity_types["ORGANISATION"].fields) == 6
        assert len(config.entity_types["PROCEDURE"].fields) == 7


# ---------------------------------------------------------------------------
# TC-002 — Reject configuration with undeclared namespace prefix
# ---------------------------------------------------------------------------


class TestRDFMappingConfigUndeclaredPrefix:
    def test_undeclared_prefix_in_rdf_type(self):
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["rdf_type"] = "foo:Organization"

        with pytest.raises(ValidationError, match="foo"):
            RDFMappingConfig(**data)

    def test_undeclared_prefix_in_field_path(self):
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = "xyz:something"

        with pytest.raises(ValidationError, match="xyz"):
            RDFMappingConfig(**data)

    def test_undeclared_prefix_in_second_segment_of_multi_hop_path(self):
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = (
            "epo:address/unk:postCode"
        )

        with pytest.raises(ValidationError, match="unk"):
            RDFMappingConfig(**data)


# ---------------------------------------------------------------------------
# TC-001 edge cases — Structural validation
# ---------------------------------------------------------------------------


class TestRDFMappingConfigStructural:
    def test_rejects_empty_entity_types(self):
        data = {"namespaces": MINIMAL_NAMESPACES, "entity_types": {}}

        with pytest.raises(ValidationError):
            RDFMappingConfig(**data)

    def test_rejects_missing_namespaces(self):
        data = {
            "entity_types": {
                "ORGANISATION": {
                    "rdf_type": "org:Organization",
                    "entity_label_field": "legal_name",
                    "fields": ORGANISATION_FIELDS,
                }
            }
        }

        with pytest.raises(ValidationError):
            RDFMappingConfig(**data)

    def test_rejects_empty_fields_on_entity_type(self):
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["fields"] = {}

        with pytest.raises(ValidationError):
            RDFMappingConfig(**data)

    def test_rejects_invalid_property_path_syntax(self):
        """'not a path' has no colon — not a valid prefix:localName segment."""
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = "not a path"

        with pytest.raises(ValidationError):
            RDFMappingConfig(**data)

    def test_rejects_url_style_property_path(self):
        """'epo://bad' contains :// — splits to an empty segment which is invalid."""
        data = minimal_config()
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = "epo://bad"

        with pytest.raises(ValidationError):
            RDFMappingConfig(**data)


# ---------------------------------------------------------------------------
# TC-003b — Entity type lookup by short key
# ---------------------------------------------------------------------------


class TestRDFMappingConfigGetEntityTypeConfig:
    def _config(self) -> RDFMappingConfig:
        return RDFMappingConfig(**minimal_config())

    def test_returns_config_for_known_key(self):
        config = self._config()
        result = config.get_entity_type_config("ORGANISATION")

        assert isinstance(result, EntityTypeConfig)
        assert result.rdf_type == "org:Organization"

    def test_raises_for_unknown_key(self):
        config = self._config()

        with pytest.raises(UnsupportedEntityTypeError) as exc_info:
            config.get_entity_type_config("UNKNOWN_TYPE")

        assert "UNKNOWN_TYPE" in exc_info.value.message

    def test_lookup_is_case_sensitive(self):
        config = self._config()

        with pytest.raises(UnsupportedEntityTypeError):
            config.get_entity_type_config("organisation")


# ---------------------------------------------------------------------------
# TC-003 — Entity type URI resolution
# ---------------------------------------------------------------------------


class TestRDFMappingConfigResolveEntityType:
    def _config(self) -> RDFMappingConfig:
        return RDFMappingConfig(**minimal_config())

    def test_resolves_known_uri_to_entity_type_config(self):
        config = self._config()
        result = config.resolve_entity_type("http://www.w3.org/ns/org#Organization")

        assert isinstance(result, EntityTypeConfig)
        assert result.rdf_type == "org:Organization"

    def test_raises_for_unknown_uri(self):
        config = self._config()

        with pytest.raises(UnsupportedEntityTypeError) as exc_info:
            config.resolve_entity_type("http://example.org/unknown#PersonEntity")

        assert "http://example.org/unknown#PersonEntity" in exc_info.value.message

    def test_resolves_second_entity_type_when_two_configured(self):
        extra = {
            "PROCEDURE": {
                "rdf_type": "epo:Procedure",
                "entity_label_field": "title",
                "fields": {"title": "epo:hasTitle"},
            }
        }
        config = RDFMappingConfig(**minimal_config(extra_types=extra))

        result = config.resolve_entity_type(
            "http://data.europa.eu/a4g/ontology#Procedure"
        )

        assert result.rdf_type == "epo:Procedure"
