"""
Step definitions for: parser_configuration.feature

Feature: Parser Configuration Loading and Entity Type Resolution
  Covers four behaviours:
    1. Load valid YAML configurations (single and multi-type).
    2. Reject configurations with undeclared namespace prefixes.
    3. Reject configurations with structural problems (empty maps, invalid paths).
    4. Resolve entity type URI to its configuration entry (match / no-match).

  These steps operate on RDFMappingConfig and RDFConfigReader directly.
  No RDF parsing or external services required.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from pytest_bdd import given, parsers, scenario, then, when

from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader
from ers.rdf_mention_parser.domain.exceptions import UnsupportedEntityTypeError
from ers.rdf_mention_parser.domain.rdf_mapping_config import EntityTypeConfig, RDFMappingConfig

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent / "rdf_mention_parser" / "parser_configuration.feature"
)


@scenario(FEATURE_FILE, "Load a valid parser configuration")
def test_load_valid_config():
    pass


@scenario(FEATURE_FILE, "Reject a configuration with an undeclared namespace prefix")
def test_reject_undeclared_prefix():
    pass


@scenario(FEATURE_FILE, "Reject a configuration with structural problems")
def test_reject_structural_problems():
    pass


@scenario(FEATURE_FILE, "Resolve an entity type URI to its configuration entry")
def test_resolve_entity_type_uri():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Reusable YAML building blocks
# ---------------------------------------------------------------------------

_FOUR_NAMESPACES = {
    "org": "http://www.w3.org/ns/org#",
    "epo": "http://data.europa.eu/a4g/ontology#",
    "cccev": "http://data.europa.eu/m8g/",
    "locn": "http://www.w3.org/ns/locn#",
}

_ORGANISATION_FIELDS_6 = {
    "legal_name": "epo:hasLegalName",
    "country_code": "cccev:registeredAddress/epo:hasCountryCode",
    "nuts_code": "cccev:registeredAddress/epo:hasNutsCode",
    "post_code": "cccev:registeredAddress/locn:postCode",
    "post_name": "cccev:registeredAddress/locn:postName",
    "thoroughfare": "cccev:registeredAddress/locn:thoroughfare",
}

# Minimal second entity type using only the four base namespaces.
_SECOND_ENTITY_TYPE = {
    "PROCEDURE": {
        "rdf_type": "epo:Procedure",
        "fields": {"title": "epo:hasTitle"},
    }
}


def _base_valid_config(
    namespace_count: int, type_count: int, entity_type: str, field_count: int
) -> dict:
    """Build a valid YAML dict to spec: namespace_count ns, type_count entity types,
    entity_type has field_count fields."""
    assert namespace_count == 4, "Only 4-namespace configs are currently supported by this step"
    assert entity_type == "ORGANISATION", "Only ORGANISATION primary type is currently supported"
    assert field_count == 6, "Only 6-field ORGANISATION configs are currently supported"

    entity_types = {
        "ORGANISATION": {
            "rdf_type": "org:Organization",
            "fields": dict(_ORGANISATION_FIELDS_6),
        }
    }
    if type_count == 2:
        entity_types.update(_SECOND_ENTITY_TYPE)

    return {"namespaces": dict(_FOUR_NAMESPACES), "entity_types": entity_types}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the parser configuration loader is available")
def config_loader_available(ctx):
    ctx["config"] = None
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a YAML configuration with {namespace_count:d} namespace prefixes, "
        "{type_count:d} entity types, and {field_count:d} field mappings "
        'for "{entity_type}"'
    )
)
def valid_yaml_config(ctx, namespace_count, type_count, field_count, entity_type):
    ctx["yaml_content"] = _base_valid_config(namespace_count, type_count, entity_type, field_count)


@given(
    parsers.parse(
        'a YAML configuration where {location} uses prefix "{prefix}" not declared in namespaces'
    )
)
def yaml_with_undeclared_prefix(ctx, location, prefix):
    data = _base_valid_config(4, 1, "ORGANISATION", 6)

    if location == "a field property path":
        data["entity_types"]["ORGANISATION"]["fields"]["bad_field"] = f"{prefix}:something"
    elif location == "the rdf_type":
        data["entity_types"]["ORGANISATION"]["rdf_type"] = f"{prefix}:Organization"
    elif location == "the second segment of a multi-hop field path":
        data["entity_types"]["ORGANISATION"]["fields"]["bad_field"] = (
            f"epo:address/{prefix}:postCode"
        )

    ctx["yaml_content"] = data


@given(parsers.parse('a YAML configuration where "{structural_problem}"'))
def yaml_with_structural_problem(ctx, structural_problem):
    data = _base_valid_config(4, 1, "ORGANISATION", 6)

    if structural_problem.startswith("entity_types is an empty map"):
        data["entity_types"] = {}
    elif structural_problem.startswith("the ORGANISATION entry has an empty fields map"):
        data["entity_types"]["ORGANISATION"]["fields"] = {}
    elif structural_problem.startswith("the namespaces section is missing entirely"):
        del data["namespaces"]
    elif structural_problem.startswith("a field value contains an invalid property path syntax"):
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = "not a path"
    elif structural_problem.startswith("a field value uses double slashes in the property path"):
        data["entity_types"]["ORGANISATION"]["fields"]["bad"] = "epo://bad"

    ctx["yaml_content"] = data


@given(parsers.parse('a parser configuration with ORGANISATION mapped to "{rdf_type}"'))
def config_with_organisation_mapped(ctx, rdf_type):
    data = {
        "namespaces": dict(_FOUR_NAMESPACES),
        "entity_types": {
            "ORGANISATION": {
                "rdf_type": rdf_type,
                "fields": dict(_ORGANISATION_FIELDS_6),
            }
        },
    }
    ctx["config"] = RDFMappingConfig(**data)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the configuration is loaded")
def load_configuration(ctx):
    try:
        ctx["config"] = RDFConfigReader.from_string(yaml.dump(ctx["yaml_content"]))
    except (ValidationError, TypeError, KeyError) as exc:
        ctx["raised_exception"] = exc


@when(parsers.parse('entity type URI "{entity_type_uri}" is resolved'))
def resolve_entity_type_uri(ctx, entity_type_uri):
    try:
        ctx["result"] = ctx["config"].resolve_entity_type(entity_type_uri)
    except UnsupportedEntityTypeError as exc:
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("a parser configuration is created")
def config_created(ctx):
    assert ctx.get("raised_exception") is None, f"Unexpected error: {ctx['raised_exception']}"
    assert ctx["config"] is not None
    assert isinstance(ctx["config"], RDFMappingConfig)


@then(
    parsers.parse(
        "it contains {namespace_count:d} namespace prefixes and {type_count:d} entity types"
    )
)
def config_has_counts(ctx, namespace_count, type_count):
    assert len(ctx["config"].namespaces) == namespace_count
    assert len(ctx["config"].entity_types) == type_count


@then(
    parsers.parse(
        'the "{entity_type}" entry has {field_count:d} field mappings '
        "each associating a name with a property path"
    )
)
def entity_type_has_fields(ctx, entity_type, field_count):
    fields = ctx["config"].entity_types[entity_type].fields
    assert len(fields) == field_count
    for name, path in fields.items():
        assert isinstance(name, str)
        assert isinstance(path, str)
        assert ":" in path  # every valid property path segment contains a prefix colon


@then("a configuration validation error is raised")
def config_validation_error(ctx):
    assert ctx.get("raised_exception") is not None, (
        "Expected a validation error but none was raised"
    )
    assert isinstance(ctx["raised_exception"], (ValidationError, TypeError, KeyError))


@then(parsers.parse("{resolution_outcome}"))
def assert_resolution_outcome(ctx, resolution_outcome):
    if "configuration is returned" in resolution_outcome:
        assert ctx.get("raised_exception") is None, (
            f"Unexpected error: {ctx.get('raised_exception')}"
        )
        assert ctx.get("result") is not None
        assert isinstance(ctx["result"], EntityTypeConfig)
    elif "unsupported entity type error is raised" in resolution_outcome:
        assert ctx.get("raised_exception") is not None
        assert isinstance(ctx["raised_exception"], UnsupportedEntityTypeError)
