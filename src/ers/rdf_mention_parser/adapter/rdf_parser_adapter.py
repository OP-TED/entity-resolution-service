import rdflib
from rdflib import RDF, Graph, URIRef

from ers.rdf_mention_parser.domain.exceptions import MalformedRDFError, UnsupportedContentTypeError

_CONTENT_TYPE_FORMAT: dict[str, str] = {
    "text/turtle": "turtle",
    "application/rdf+xml": "xml",
}


class RDFParserAdapter:
    """Thin infrastructure wrapper around RDFLib.

    Responsibilities:
    - Parse RDF strings into graphs (text/turtle, application/rdf+xml).
    - Execute SPARQL SELECT queries and return plain-dict result rows.
    - Check whether a graph contains a subject of a given RDF type.

    This adapter does NOT build SPARQL queries and does NOT contain business logic.
    All domain exceptions raised here originate from infrastructure failures
    (parse errors, unsupported formats).
    """

    def parse_to_graph(self, content: str, content_type: str) -> Graph:
        """Parse an RDF string into an RDFLib Graph.

        Args:
            content: Raw RDF string.
            content_type: MIME type — ``text/turtle`` or ``application/rdf+xml``.

        Returns:
            Populated rdflib.Graph.

        Raises:
            UnsupportedContentTypeError: If content_type is not supported.
            MalformedRDFError: If the content cannot be parsed.
        """
        if content_type not in _CONTENT_TYPE_FORMAT:
            raise UnsupportedContentTypeError(content_type)

        fmt = _CONTENT_TYPE_FORMAT[content_type]
        graph = Graph()
        try:
            graph.parse(data=content, format=fmt)
        except Exception as exc:
            raise MalformedRDFError(content_type) from exc

        return graph

    def execute_sparql(self, graph: Graph, query: str) -> list[dict[str, str | None]]:
        """Execute a SPARQL SELECT query and return the result rows as plain dicts.

        Args:
            graph: The RDFLib graph to query.
            query: A SPARQL SELECT query string.

        Returns:
            List of result rows, each mapping variable name → string value (or None).
            Empty list when the query matches nothing.
        """
        results = graph.query(query)
        rows = []
        for row in results:
            row_dict = {str(var): (str(row[var]) if row[var] is not None else None) for var in results.vars}
            rows.append(row_dict)
        return rows

    def has_entity_of_type(self, graph: Graph, type_uri: str) -> bool:
        """Return True if the graph contains at least one subject with the given rdf:type.

        Args:
            graph: The RDFLib graph to inspect.
            type_uri: Full URI string, e.g. ``http://www.w3.org/ns/org#Organization``.

        Returns:
            True if at least one matching subject exists.
        """
        return any(True for _ in graph.subjects(RDF.type, URIRef(type_uri)))
