import logging
from string import Template
from typing import Any

from erspec.models.core import EntityMention

from ers import config
from ers.commons.adapters.tracing import trace_function
from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader
from ers.rdf_mention_parser.adapter.rdf_parser_adapter import RDFParserAdapter
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError,
    EmptyExtractionError,
    EntityTypeMismatchError,
    MultipleEntitiesFoundError,
)
from ers.rdf_mention_parser.domain.rdf_mapping_config import EntityTypeConfig, RDFMappingConfig

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
        variables="?entity " + " ".join(f"?{name}" for name in entity_config.fields),
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

    Errors are fatal (raised, never swallowed). Individual fields may be ``None``
    when absent in the RDF — only a completely empty extraction is rejected.
    """

    def __init__(self, config: RDFMappingConfig, adapter: RDFParserAdapter) -> None:
        self._config = config
        self._adapter = adapter

    @staticmethod
    def _validate_content_size(content: str, entity_type: str, content_type: str) -> None:
        content_bytes = content.encode("utf-8")
        max_bytes = config.ERS_PARSER_MAX_CONTENT_LENGTH
        if len(content_bytes) > max_bytes:
            logger.warning(
                "Content too large: entity_type=%s content_type=%s size=%d",
                entity_type,
                content_type,
                len(content_bytes),
            )
            raise ContentTooLargeError(max_bytes)

    @staticmethod
    def _validate_single_entity(rows: list[dict[str, Any]], entity_type: str) -> None:
        distinct_entities = {row["entity"] for row in rows if row.get("entity")}
        if len(distinct_entities) > 1:
            logger.warning(
                "Multiple entities found: entity_type=%s count=%d",
                entity_type,
                len(distinct_entities),
            )
            raise MultipleEntitiesFoundError(entity_type, len(distinct_entities))

    @staticmethod
    def _merge_rows(rows: list[dict[str, Any]], field_names: list[str]) -> dict[str, str | None]:
        merged: dict[str, str | None] = {name: None for name in field_names}
        for row in rows:
            for name in field_names:
                if merged[name] is None and row.get(name) is not None:
                    merged[name] = row[name]
        return merged

    def parse(self, entity_mention: EntityMention) -> dict[str, Any]:
        """Parse an RDF mention and return its JSON representation.

        Args:
            entity_mention: The entity mention to parse. Provides content,
                            content_type, and entity_type identifier.

        Returns:
            Dict mapping configured field names to extracted string values.
            Fields absent in the RDF are mapped to ``None``.

        Raises:
            ContentTooLargeError, UnsupportedEntityTypeError, UnsupportedContentTypeError,
            MalformedRDFError, EntityTypeMismatchError, MultipleEntitiesFoundError,
            EmptyExtractionError: see class docstring.
        """
        content = entity_mention.content
        content_type = entity_mention.content_type
        entity_type = str(entity_mention.identifiedBy.entity_type)

        self._validate_content_size(content, entity_type, content_type)

        entity_config = self._config.resolve_entity_type(entity_type)
        graph = self._adapter.parse_to_graph(content, content_type)

        prefix, local = entity_config.rdf_type.split(":", 1)
        rdf_type_uri = self._config.namespaces[prefix] + local
        if not self._adapter.has_entity_of_type(graph, rdf_type_uri):
            logger.warning("Entity type mismatch: expected=%s", entity_type)
            raise EntityTypeMismatchError(entity_type)

        query = build_sparql_query(self._config, entity_config)
        rows = self._adapter.execute_sparql(graph, query)

        if not rows:
            logger.warning("Empty extraction: entity_type=%s", entity_type)
            raise EmptyExtractionError(entity_type)

        self._validate_single_entity(rows, entity_type)

        field_names = list(entity_config.fields)
        merged = self._merge_rows(rows, field_names)

        if all(v is None for v in merged.values()):
            logger.warning("Empty extraction: entity_type=%s", entity_type)
            raise EmptyExtractionError(entity_type)

        logger.info(
            "Parsed entity_type=%s content_type=%s fields_extracted=%d",
            entity_type,
            content_type,
            sum(1 for v in merged.values() if v is not None),
        )
        return merged


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


def load_config() -> RDFMappingConfig:
    """Load the RDF mapping config from the path set in ``RDF_MENTION_CONFIG_FILE``.

    Returns:
        A validated RDFMappingConfig instance.

    Raises:
        FileNotFoundError: If the configured path does not exist.
        pydantic.ValidationError: If the config content fails validation.
    """
    return RDFConfigReader.from_file(config.RDF_MENTION_CONFIG_FILE)


@trace_function(span_name="mention_parser.parse")
def parse_entity_mention(
    entity_mention: EntityMention,
    config: RDFMappingConfig,
) -> dict[str, Any]:
    """Parse a raw RDF entity mention into a JSON representation.

    Args:
        entity_mention: The entity mention to parse.
        config: Validated RDF mapping configuration.

    Returns:
        Dict mapping configured field names to extracted string values.

    Raises:
        ContentTooLargeError, UnsupportedEntityTypeError, UnsupportedContentTypeError,
        MalformedRDFError, EntityTypeMismatchError, MultipleEntitiesFoundError,
        EmptyExtractionError: see MentionParserService.parse.
    """
    service = MentionParserService(config, RDFParserAdapter())
    return service.parse(entity_mention)
