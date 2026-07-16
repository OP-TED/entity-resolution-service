"""Unit tests for RDFConfigReader adapter.

Covers IT-003 (config from file/string loads and resolves correctly).
"""

import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

# ---------------------------------------------------------------------------
# from_string
# ---------------------------------------------------------------------------


class TestRDFConfigReaderFromString:
    def test_parses_valid_yaml_string(self, sample_rdf_mapping: str):
        config = RDFConfigReader.from_string(sample_rdf_mapping)

        assert isinstance(config, RDFMappingConfig)
        assert "ORGANISATION" in config.entity_types
        assert "PROCEDURE" in config.entity_types

    def test_returns_correct_namespace_count(self, sample_rdf_mapping: str):
        config = RDFConfigReader.from_string(sample_rdf_mapping)

        assert len(config.namespaces) == 7  # adms, cccev, dct, epo, locn, org, skos

    def test_raises_validation_error_for_invalid_config(self):
        bad_yaml = textwrap.dedent("""
            namespaces:
              org: "http://www.w3.org/ns/org#"
            entity_types: {}
        """)

        with pytest.raises(ValidationError):
            RDFConfigReader.from_string(bad_yaml)

    def test_raises_yaml_error_for_malformed_yaml(self):
        with pytest.raises(yaml.YAMLError):
            RDFConfigReader.from_string("key: [unclosed")

    def test_organisation_fields_match_sample(self, sample_rdf_mapping: str):
        config = RDFConfigReader.from_string(sample_rdf_mapping)
        fields = config.entity_types["ORGANISATION"].fields

        assert fields["legal_name"] == "epo:hasLegalName"
        assert fields["country_code"] == "cccev:registeredAddress/epo:hasCountryCode"

    def test_procedure_fields_match_sample(self, sample_rdf_mapping: str):
        config = RDFConfigReader.from_string(sample_rdf_mapping)
        fields = config.entity_types["PROCEDURE"].fields

        assert fields["title"] == "dct:title"
        assert fields["identifier"] == "adms:identifier/skos:notation"


# ---------------------------------------------------------------------------
# from_file
# ---------------------------------------------------------------------------


class TestRDFConfigReaderFromFile:
    def test_loads_from_existing_yaml_file(self, tmp_path: Path, sample_rdf_mapping: str):
        config_file = tmp_path / "rdf_mapping.yaml"
        config_file.write_text(sample_rdf_mapping, encoding="utf-8")

        config = RDFConfigReader.from_file(config_file)

        assert isinstance(config, RDFMappingConfig)
        assert "ORGANISATION" in config.entity_types

    def test_raises_file_not_found_for_missing_path(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.yaml"

        with pytest.raises(FileNotFoundError, match="does_not_exist.yaml"):
            RDFConfigReader.from_file(missing)

    def test_accepts_string_path(self, tmp_path: Path, sample_rdf_mapping: str):
        config_file = tmp_path / "rdf_mapping.yaml"
        config_file.write_text(sample_rdf_mapping, encoding="utf-8")

        config = RDFConfigReader.from_file(str(config_file))

        assert isinstance(config, RDFMappingConfig)

    def test_type_resolution_works_after_file_load(self, tmp_path: Path, sample_rdf_mapping: str):
        config_file = tmp_path / "rdf_mapping.yaml"
        config_file.write_text(sample_rdf_mapping, encoding="utf-8")
        config = RDFConfigReader.from_file(config_file)

        result = config.resolve_entity_type("http://www.w3.org/ns/org#Organization")

        assert result.rdf_type == "org:Organization"


# ---------------------------------------------------------------------------
# from_file — path-based loading (covers what was from_env_or_default)
# ---------------------------------------------------------------------------


class TestRDFConfigReaderFromFilePath:
    def test_loads_from_explicit_path(self, tmp_path: Path, sample_rdf_mapping: str):
        config_file = tmp_path / "custom.yaml"
        config_file.write_text(sample_rdf_mapping, encoding="utf-8")

        config = RDFConfigReader.from_file(config_file)

        assert isinstance(config, RDFMappingConfig)
        assert "ORGANISATION" in config.entity_types

    def test_raises_file_not_found_for_missing_path(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            RDFConfigReader.from_file(tmp_path / "missing.yaml")
