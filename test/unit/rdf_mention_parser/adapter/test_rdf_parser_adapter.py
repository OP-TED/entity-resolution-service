"""Unit tests for RDFParserAdapter.

Covers TC-004, TC-005, TC-006, TC-007 from the EPIC.
"""

import pytest

from ers.rdf_mention_parser.adapter.rdf_parser_adapter import RDFParserAdapter
from ers.rdf_mention_parser.domain.exceptions import MalformedRDFError, UnsupportedContentTypeError

# ---------------------------------------------------------------------------
# Minimal RDF content fixtures
# ---------------------------------------------------------------------------

_ORG_TURTLE = """\
@prefix org: <http://www.w3.org/ns/org#> .
@prefix epo: <http://data.europa.eu/a4g/ontology#> .
@prefix ex: <http://example.org/> .

ex:org1 a org:Organization ;
    epo:hasLegalName "Test Organisation" .
"""

_ORG_RDFXML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:org="http://www.w3.org/ns/org#"
         xmlns:epo="http://data.europa.eu/a4g/ontology#">
  <org:Organization rdf:about="http://example.org/org1">
    <epo:hasLegalName>Test Organisation</epo:hasLegalName>
  </org:Organization>
</rdf:RDF>
"""

_SPARQL_LEGAL_NAME = """\
PREFIX org: <http://www.w3.org/ns/org#>
PREFIX epo: <http://data.europa.eu/a4g/ontology#>
SELECT ?legal_name
WHERE {
  ?entity a org:Organization .
  OPTIONAL { ?entity epo:hasLegalName ?legal_name . }
} LIMIT 1
"""


@pytest.fixture
def adapter() -> RDFParserAdapter:
    return RDFParserAdapter()


# ---------------------------------------------------------------------------
# TC-004 — parse_to_graph with Turtle
# ---------------------------------------------------------------------------


class TestParseToGraphTurtle:
    def test_returns_graph_with_triples(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        assert len(graph) > 0

    def test_graph_contains_org_type_triple(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        assert adapter.has_entity_of_type(graph, "http://www.w3.org/ns/org#Organization")

    def test_raises_malformed_rdf_error_on_bad_turtle(self, adapter):
        with pytest.raises(MalformedRDFError) as exc_info:
            adapter.parse_to_graph("this is { not valid turtle !!!", "text/turtle")
        assert exc_info.value.content_type == "text/turtle"

    def test_raises_malformed_rdf_error_on_empty_string(self, adapter):
        # Empty string is technically valid Turtle (empty graph), so use truncated content
        with pytest.raises(MalformedRDFError):
            adapter.parse_to_graph("@prefix : <> . :s :p", "text/turtle")  # truncated triple


# ---------------------------------------------------------------------------
# TC-005 — parse_to_graph with RDF/XML
# ---------------------------------------------------------------------------


class TestParseToGraphRDFXML:
    def test_returns_graph_with_triples(self, adapter):
        graph = adapter.parse_to_graph(_ORG_RDFXML, "application/rdf+xml")
        assert len(graph) > 0

    def test_graph_contains_org_type_triple(self, adapter):
        graph = adapter.parse_to_graph(_ORG_RDFXML, "application/rdf+xml")
        assert adapter.has_entity_of_type(graph, "http://www.w3.org/ns/org#Organization")

    def test_raises_malformed_rdf_error_on_bad_xml(self, adapter):
        with pytest.raises(MalformedRDFError) as exc_info:
            adapter.parse_to_graph("<unclosed xml", "application/rdf+xml")
        assert exc_info.value.content_type == "application/rdf+xml"


# ---------------------------------------------------------------------------
# TC-006 — parse_to_graph with unsupported content type
# ---------------------------------------------------------------------------


class TestParseToGraphUnsupportedContentType:
    def test_raises_for_json(self, adapter):
        with pytest.raises(UnsupportedContentTypeError) as exc_info:
            adapter.parse_to_graph("{}", "application/json")
        assert exc_info.value.content_type == "application/json"

    def test_raises_for_plain_text(self, adapter):
        with pytest.raises(UnsupportedContentTypeError):
            adapter.parse_to_graph("hello", "text/plain")

    def test_raises_for_empty_content_type(self, adapter):
        with pytest.raises(UnsupportedContentTypeError):
            adapter.parse_to_graph(_ORG_TURTLE, "")


# ---------------------------------------------------------------------------
# TC-007 — execute_sparql
# ---------------------------------------------------------------------------


class TestExecuteSparql:
    def test_returns_one_row_for_matching_entity(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        rows = adapter.execute_sparql(graph, _SPARQL_LEGAL_NAME)

        assert len(rows) == 1
        assert rows[0]["legal_name"] == "Test Organisation"

    def test_returns_empty_list_when_no_match(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        query = """\
PREFIX ex: <http://example.org/>
SELECT ?name
WHERE { ?s a ex:NonExistentType . OPTIONAL { ?s ex:name ?name . } } LIMIT 1
"""
        rows = adapter.execute_sparql(graph, query)
        assert rows == []

    def test_returns_none_for_absent_optional_field(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        query = """\
PREFIX org: <http://www.w3.org/ns/org#>
PREFIX epo: <http://data.europa.eu/a4g/ontology#>
SELECT ?legal_name ?missing_field
WHERE {
  ?entity a org:Organization .
  OPTIONAL { ?entity epo:hasLegalName ?legal_name . }
  OPTIONAL { ?entity epo:nonExistent ?missing_field . }
} LIMIT 1
"""
        rows = adapter.execute_sparql(graph, query)
        assert len(rows) == 1
        assert rows[0]["legal_name"] == "Test Organisation"
        assert rows[0]["missing_field"] is None


# ---------------------------------------------------------------------------
# has_entity_of_type
# ---------------------------------------------------------------------------


class TestHasEntityOfType:
    def test_returns_true_for_existing_type(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        assert adapter.has_entity_of_type(graph, "http://www.w3.org/ns/org#Organization") is True

    def test_returns_false_for_absent_type(self, adapter):
        graph = adapter.parse_to_graph(_ORG_TURTLE, "text/turtle")
        assert adapter.has_entity_of_type(graph, "http://example.org/Person") is False
