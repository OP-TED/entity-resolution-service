"""
Step definitions for: rdf_parsing.feature

Feature: Parse RDF Entity Mention into JSON Representation
"""

from pathlib import Path

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers import config
from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader
from ers.rdf_mention_parser.adapter.rdf_parser_adapter import RDFParserAdapter
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError,
    EmptyExtractionError,
    EntityTypeMismatchError,
    MalformedRDFError,
    UnsupportedContentTypeError,
    UnsupportedEntityTypeError,
)
from ers.rdf_mention_parser.services.mention_parser_service import MentionParserService

MAX_CONTENT_LENGTH = config.ERS_PARSER_MAX_CONTENT_LENGTH

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "rdf_parsing.feature")


@scenario(FEATURE_FILE, "Extract configured fields from valid RDF content")
def test_extract_configured_fields():
    pass


@scenario(FEATURE_FILE, "Ignore RDF triples not declared in the configuration")
def test_ignore_extra_triples():
    pass


@scenario(
    FEATURE_FILE,
    "Extract fields from multi-hop property paths where intermediate nodes exist but leaf is absent",
)
def test_multi_hop_partial():
    pass


@scenario(FEATURE_FILE, "Handle content size boundaries")
def test_content_size_boundaries():
    pass


@scenario(FEATURE_FILE, "Reject invalid input with the appropriate error")
def test_reject_invalid_input():
    pass


# ---------------------------------------------------------------------------
# Shared context + config
# ---------------------------------------------------------------------------

_NAMESPACES = {
    "org": "http://www.w3.org/ns/org#",
    "epo": "http://data.europa.eu/a4g/ontology#",
    "cccev": "http://data.europa.eu/m8g/",
    "locn": "http://www.w3.org/ns/locn#",
}

_ORG_FIELDS_7 = {
    "legal_name": "epo:hasLegalName",
    "country_code": "cccev:registeredAddress/epo:hasCountryCode",
    "nuts_code": "cccev:registeredAddress/epo:hasNutsCode",
    "post_code": "cccev:registeredAddress/locn:postCode",
    "post_name": "cccev:registeredAddress/locn:postName",
    "thoroughfare": "cccev:registeredAddress/locn:thoroughfare",
    "full_address": "cccev:registeredAddress/locn:fullAddress",
}

_TURTLE_PREFIXES = """\
@prefix org: <http://www.w3.org/ns/org#> .
@prefix epo: <http://data.europa.eu/a4g/ontology#> .
@prefix cccev: <http://data.europa.eu/m8g/> .
@prefix locn: <http://www.w3.org/ns/locn#> .
@prefix ex: <http://example.org/> .
"""

# Canonical 7-field Organisation Turtle
_ORG_7_FIELDS_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    epo:hasLegalName "Test Organisation" ;
    cccev:registeredAddress ex:addr1 .
ex:addr1 a locn:Address ;
    epo:hasCountryCode <http://publications.europa.eu/resource/authority/country/DEU> ;
    epo:hasNutsCode <http://data.europa.eu/nuts/code/DE1> ;
    locn:postCode "10115" ;
    locn:postName "Berlin" ;
    locn:thoroughfare "Unter den Linden 1" ;
    locn:fullAddress "Unter den Linden 1, 10115 Berlin" .
"""
)

# 2-field: legal_name + country_code only
_ORG_2_FIELDS_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    epo:hasLegalName "Partial Org" ;
    cccev:registeredAddress ex:addr1 .
ex:addr1 a locn:Address ;
    epo:hasCountryCode <http://publications.europa.eu/resource/authority/country/DEU> .
"""
)

# 1-field: legal_name only
_ORG_1_FIELD_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    epo:hasLegalName "Minimal Org" .
"""
)

# 7 configured fields + 3 extra triples not in the configuration
_ORG_WITH_EXTRAS_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    epo:hasLegalName "Extra Org" ;
    epo:hasPrimaryContactPoint ex:cp1 ;
    epo:hasRegistrationCountry <http://publications.europa.eu/resource/authority/country/DEU> ;
    cccev:registeredAddress ex:addr1 .
ex:addr1 a locn:Address ;
    epo:hasCountryCode <http://publications.europa.eu/resource/authority/country/DEU> ;
    epo:hasNutsCode <http://data.europa.eu/nuts/code/DE1> ;
    locn:postCode "10115" ;
    locn:postName "Berlin" ;
    locn:thoroughfare "Unter den Linden 1" ;
    locn:fullAddress "Unter den Linden 1, 10115 Berlin" ;
    locn:adminUnitL1 "DE" .
"""
)

# Address node present but locn:postCode absent
_ORG_ADDRESS_NO_POSTCODE_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    epo:hasLegalName "No Postcode Org" ;
    cccev:registeredAddress ex:addr1 .
ex:addr1 a locn:Address ;
    epo:hasCountryCode <http://publications.europa.eu/resource/authority/country/DEU> ;
    locn:postName "Berlin" ;
    locn:thoroughfare "Unter den Linden 1" .
"""
)

# Person entity — wrong type for org config
_PERSON_TTL = (
    _TURTLE_PREFIXES
    + """
ex:person1 a <http://xmlns.com/foaf/0.1/Person> ;
    <http://xmlns.com/foaf/0.1/name> "John Doe" .
"""
)

# Organisation with no configured fields (uses unknown properties only)
_ORG_NO_CONFIGURED_FIELDS_TTL = (
    _TURTLE_PREFIXES
    + """
ex:org1 a org:Organization ;
    <http://example.org/someUnknownProp> "value" .
"""
)

# RDF/XML equivalent of _ORG_7_FIELDS_TTL
_ORG_7_FIELDS_RDFXML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:org="http://www.w3.org/ns/org#"
         xmlns:epo="http://data.europa.eu/a4g/ontology#"
         xmlns:cccev="http://data.europa.eu/m8g/"
         xmlns:locn="http://www.w3.org/ns/locn#">
  <org:Organization rdf:about="http://example.org/org1">
    <epo:hasLegalName>Test Organisation</epo:hasLegalName>
    <cccev:registeredAddress>
      <locn:Address rdf:about="http://example.org/addr1">
        <epo:hasCountryCode rdf:resource="http://publications.europa.eu/resource/authority/country/DEU"/>
        <epo:hasNutsCode rdf:resource="http://data.europa.eu/nuts/code/DE1"/>
        <locn:postCode>10115</locn:postCode>
        <locn:postName>Berlin</locn:postName>
        <locn:thoroughfare>Unter den Linden 1</locn:thoroughfare>
        <locn:fullAddress>Unter den Linden 1, 10115 Berlin</locn:fullAddress>
      </locn:Address>
    </cccev:registeredAddress>
  </org:Organization>
</rdf:RDF>
"""


def _build_padded_turtle(target_bytes: int) -> str:
    """Build a valid Turtle string whose UTF-8 encoding is exactly target_bytes."""
    base = _ORG_1_FIELD_TTL
    base_len = len(base.encode("utf-8"))
    # A Turtle comment: # followed by padding chars and a newline
    comment_overhead = 3  # "# " (2) + "\n" (1)
    pad_chars = target_bytes - base_len - comment_overhead
    if pad_chars < 0:
        raise ValueError("Target size is smaller than the base content")
    return f"# {'x' * pad_chars}\n" + base


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the parser is configured for ORGANISATION with 7 field mappings")
def parser_configured(ctx, sample_rdf_mapping):
    config = RDFConfigReader.from_string(sample_rdf_mapping)
    adapter = RDFParserAdapter()
    ctx["service"] = MentionParserService(config, adapter)
    ctx["config"] = config


@given(parsers.parse('the entity type is "{entity_type}"'))
def default_entity_type(ctx, entity_type):
    ctx["entity_type"] = entity_type


# ---------------------------------------------------------------------------
# Given — valid RDF content
# ---------------------------------------------------------------------------

_CONTENT_BY_COUNT = {
    7: {"text/turtle": _ORG_7_FIELDS_TTL, "application/rdf+xml": _ORG_7_FIELDS_RDFXML},
    2: {"text/turtle": _ORG_2_FIELDS_TTL},
    1: {"text/turtle": _ORG_1_FIELD_TTL},
}


@given(
    parsers.parse(
        'an RDF payload in "{content_type}" format describing an Organisation '
        "with {present_count:d} of 7 configured fields present"
    )
)
def rdf_payload_with_n_fields(ctx, content_type, present_count):
    ctx["content_type"] = content_type
    ctx["present_count"] = present_count
    ctx["content"] = _CONTENT_BY_COUNT[present_count][content_type]


@given(
    "an RDF Turtle payload describing an Organisation with all 7 configured "
    "fields and 3 additional properties not in the configuration"
)
def rdf_payload_with_extra_triples(ctx):
    ctx["content_type"] = "text/turtle"
    ctx["content"] = _ORG_WITH_EXTRAS_TTL


@given(
    "an RDF Turtle payload where the Organisation has a registered address "
    "node but the post code property is absent"
)
def rdf_payload_multi_hop_partial(ctx):
    ctx["content_type"] = "text/turtle"
    ctx["content"] = _ORG_ADDRESS_NO_POSTCODE_TTL


# ---------------------------------------------------------------------------
# Given — content size boundaries
# ---------------------------------------------------------------------------


@given(parsers.parse('an RDF Turtle payload whose byte size is "{size_description}"'))
def rdf_payload_at_size_boundary(ctx, size_description):
    ctx["content_type"] = "text/turtle"
    if size_description == "exactly 1 MB":
        ctx["content"] = _build_padded_turtle(MAX_CONTENT_LENGTH)
    elif size_description == "1 byte over 1 MB":
        ctx["content"] = _build_padded_turtle(MAX_CONTENT_LENGTH + 1)


# ---------------------------------------------------------------------------
# Given — invalid input
# ---------------------------------------------------------------------------


@given(parsers.parse('"{invalid_input}"'))
def invalid_rdf_input(ctx, invalid_input):
    ctx["content_type"] = "text/turtle"  # default

    if "application/json" in invalid_input:
        ctx["content_type"] = "application/json"
        ctx["content"] = '{"key": "value"}'
    elif "malformed syntax" in invalid_input:
        ctx["content"] = "@prefix : <> . :s :p"  # truncated triple
    elif "Person, not an Organisation" in invalid_input:
        ctx["content"] = _PERSON_TTL
    elif "none of the 7 configured fields" in invalid_input:
        ctx["content"] = _ORG_NO_CONFIGURED_FIELDS_TTL
    elif "valid RDF Turtle payload describing an Organisation" in invalid_input:
        ctx["content"] = _ORG_1_FIELD_TTL  # valid org, but entity_type_uri will be wrong


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the mention is parsed")
def parse_mention_default(ctx):
    try:
        entity_mention = EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id="test-source",
                request_id="test-request-001",
                entity_type=ctx["entity_type"],
            ),
            content=ctx["content"],
            content_type=ctx["content_type"],
        )
        ctx["result"] = ctx["service"].parse(entity_mention)
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('the mention is parsed for entity type "{entity_type}"'))
def parse_mention_with_type(ctx, entity_type):
    try:
        entity_mention = EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id="test-source",
                request_id="test-request-001",
                entity_type=entity_type,
            ),
            content=ctx["content"],
            content_type=ctx["content_type"],
        )
        ctx["result"] = ctx["service"].parse(entity_mention)
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("a JSON representation is returned with {count:d} extracted fields"))
def json_with_n_fields(ctx, count):
    assert ctx["raised_exception"] is None, f"Unexpected error: {ctx['raised_exception']}"
    assert ctx["result"] is not None
    non_none = {k: v for k, v in ctx["result"].items() if v is not None}
    assert len(non_none) == count


@then(parsers.parse("the remaining {count:d} configured fields are absent"))
def remaining_fields_absent(ctx, count):
    absent = {k for k, v in ctx["result"].items() if v is None}
    assert len(absent) == count


@then("no additional fields beyond the configured mappings appear in the result")
def no_extra_fields_in_result(ctx):
    config_fields = set(ctx["config"].entity_types["ORGANISATION"].fields.keys())
    assert set(ctx["result"].keys()).issubset(config_fields)


@then("a JSON representation is returned")
def json_returned(ctx):
    assert ctx["raised_exception"] is None, f"Unexpected error: {ctx['raised_exception']}"
    assert ctx["result"] is not None
    assert isinstance(ctx["result"], dict)


@then("the post_code field is absent from the result")
def post_code_absent(ctx):
    assert ctx["result"].get("post_code") is None


@then("the other address fields that are present are correctly extracted")
def other_address_fields_extracted(ctx):
    assert ctx["result"].get("country_code") is not None
    assert ctx["result"].get("post_name") is not None
    assert ctx["result"].get("thoroughfare") is not None


@then(parsers.parse('"{outcome}"'))
def assert_outcome(ctx, outcome):
    if "JSON representation is returned" in outcome:
        assert ctx["raised_exception"] is None, f"Unexpected error: {ctx['raised_exception']}"
        assert ctx["result"] is not None
    elif "content_too_large error" in outcome:
        assert isinstance(ctx["raised_exception"], ContentTooLargeError)


@then(parsers.parse('a "{error_type}" error is raised'))
def specific_error_raised(ctx, error_type):
    _error_map = {
        "content_too_large": ContentTooLargeError,
        "unsupported_content_type": UnsupportedContentTypeError,
        "malformed_rdf": MalformedRDFError,
        "entity_type_mismatch": EntityTypeMismatchError,
        "empty_extraction": EmptyExtractionError,
        "unsupported_entity_type": UnsupportedEntityTypeError,
    }
    assert ctx["raised_exception"] is not None, f"Expected {error_type} but no error was raised"
    assert isinstance(ctx["raised_exception"], _error_map[error_type]), (
        f"Expected {_error_map[error_type].__name__}, got {type(ctx['raised_exception']).__name__}: {ctx['raised_exception']}"
    )
