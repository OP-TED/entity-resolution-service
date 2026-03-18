import logging
import os
from string import Template
from typing import Any

from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader
from ers.rdf_mention_parser.adapter.rdf_parser_adapter import RDFParserAdapter
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError,
    EmptyExtractionError,
    EntityTypeMismatchError,
    MultipleEntitiesFoundError,
)
from ers.rdf_mention_parser.domain.rdf_mapping_config import EntityTypeConfig, RDFMappingConfig

MAX_CONTENT_LENGTH: int = int(os.environ.get("ERS_PARSER_MAX_CONTENT_LENGTH", 1_048_576))

logger = logging.getLogger(__name__)

_SPARQL_TEMPLATE = Template("""\
$prefixes
SELECT $variables
WHERE {
  ?entity a $rdf_type .
$optionals
}""")


def build_sparql_query(config: RDFMappingConfig, entity_config: EntityTypeConfig) -> str:
    """Build a SPARQL SELECT query from the entity type configuration.

    Generates PREFIX declarations for all declared namespaces, a required
    ``?entity a <rdf_type>`` triple, and one OPTIONAL clause per configured field.
    Property paths use prefixed notation (e.g. ``cccev:registeredAddress/epo:hasCountryCode``)
    so rdflib resolves them via the PREFIX block.

    Args:
        config: Root config providing namespace prefix → URI mappings.
        entity_config: Per-entity-type config with rdf_type and field paths.

    Returns:
        A SPARQL 1.1 SELECT query string ready for execution.
    """
    return _SPARQL_TEMPLATE.substitute(
        prefixes="\n".join(
            f"PREFIX {prefix}: <{uri}>" for prefix, uri in config.namespaces.items()
        ),
        variables=" ".join(f"?{name}" for name in entity_config.fields),
        rdf_type=entity_config.rdf_type,
        optionals="\n".join(
            f"  OPTIONAL {{ ?entity {path} ?{name} . }}"
            for name, path in entity_config.fields.items()
        ),
    )


class MentionParserService:
    """Parses a raw RDF entity mention into a JSON representation (dict).

    Orchestrates: content-length guard → entity type resolution → RDF parsing
    → entity type validation → SPARQL extraction → empty-result guard → result dict.

    All errors are fatal; no partial results are returned.
    """

    def __init__(self, config: RDFMappingConfig, adapter: RDFParserAdapter) -> None:
        self._config = config
        self._adapter = adapter

    def parse(self, content: str, content_type: str, entity_type: str) -> dict[str, Any]:
        """Parse an RDF mention and return its JSON representation.

        Args:
            content: Raw RDF string.
            content_type: MIME type (``text/turtle`` or ``application/rdf+xml``).
            entity_type: Full URI of the entity type, e.g.
                         ``http://www.w3.org/ns/org#Organization``.

        Returns:
            Dict mapping configured field names to extracted string values.
            Fields absent in the RDF are mapped to ``None``.

        Raises:
            ContentTooLargeError: Content exceeds MAX_CONTENT_LENGTH bytes.
            UnsupportedEntityTypeError: entity_type not found in config.
            UnsupportedContentTypeError: content_type not in supported set.
            MalformedRDFError: Content cannot be parsed as the declared format.
            EntityTypeMismatchError: Graph contains no entity of the declared type.
            MultipleEntitiesFoundError: Graph contains more than one entity of the declared type.
            EmptyExtractionError: All configured fields resolve to None.
        """
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_CONTENT_LENGTH:
            logger.warning(
                "Content too large: entity_type=%s content_type=%s size=%d",
                entity_type,
                content_type,
                len(content_bytes),
            )
            raise ContentTooLargeError(MAX_CONTENT_LENGTH)

        # Raises UnsupportedEntityTypeError if entity_type has no config entry.
        entity_config = self._config.resolve_entity_type(entity_type)

        # Raises UnsupportedContentTypeError or MalformedRDFError.
        graph = self._adapter.parse_to_graph(content, content_type)

        prefix, local = entity_config.rdf_type.split(":", 1)
        rdf_type_uri = self._config.namespaces[prefix] + local
        if not self._adapter.has_entity_of_type(graph, rdf_type_uri):
            logger.warning("Entity type mismatch: expected=%s", entity_type)
            raise EntityTypeMismatchError(entity_type)

        query = build_sparql_query(self._config, entity_config)
        rows = self._adapter.execute_sparql(graph, query)

        if len(rows) > 1:
            logger.warning("Multiple entities found: entity_type=%s count=%d", entity_type, len(rows))
            raise MultipleEntitiesFoundError(entity_type, len(rows))

        if not rows or all(v is None for v in rows[0].values()):
            logger.warning("Empty extraction: entity_type=%s", entity_type)
            raise EmptyExtractionError(entity_type)

        result = rows[0]
        logger.info(
            "Parsed entity_type=%s content_type=%s fields_extracted=%d",
            entity_type,
            content_type,
            sum(1 for v in result.values() if v is not None),
        )
        return result


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


def load_config() -> RDFMappingConfig:
    """Load the RDF mapping config from the environment-configured path or bundled default.

    Returns:
        A validated RDFMappingConfig instance.

    Raises:
        FileNotFoundError: If the resolved config path does not exist.
        pydantic.ValidationError: If the config content fails validation.
    """
    return RDFConfigReader.from_env_or_default()


def parse_entity_mention(
    content: str,
    content_type: str,
    entity_type: str,
    config: RDFMappingConfig,
) -> dict[str, Any]:
    """Parse a raw RDF entity mention into a JSON representation.

    Wires up the adapter and service, then delegates to MentionParserService.

    Args:
        content: Raw RDF string.
        content_type: MIME type (``text/turtle`` or ``application/rdf+xml``).
        entity_type: Full URI of the entity type.
        config: Validated RDF mapping configuration.

    Returns:
        Dict mapping configured field names to extracted string values.

    Raises:
        ContentTooLargeError, UnsupportedEntityTypeError, UnsupportedContentTypeError,
        MalformedRDFError, EntityTypeMismatchError, MultipleEntitiesFoundError,
        EmptyExtractionError: see MentionParserService.parse.
    """
    service = MentionParserService(config, RDFParserAdapter())
    return service.parse(content, content_type, entity_type)
