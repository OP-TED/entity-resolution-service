import re

from pydantic import BaseModel, field_validator, model_validator

from ers.rdf_mention_parser.domain.exceptions import UnsupportedEntityTypeError

# Matches a valid property path segment: "prefix:localName"
# Excludes URL-style values like "epo://bad" (empty segment after split) and
# free strings like "not a path" (space, no colon).
_SEGMENT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*:[a-zA-Z][a-zA-Z0-9_./-]*$")


class EntityTypeConfig(BaseModel):
    """Configuration for a single entity type: its RDF type and field-to-property-path mappings."""

    rdf_type: str
    fields: dict[str, str]

    @field_validator("fields")
    @classmethod
    def fields_not_empty(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("fields must not be empty")
        return v

    @field_validator("fields")
    @classmethod
    def validate_field_paths(cls, v: dict[str, str]) -> dict[str, str]:
        for field_name, path in v.items():
            segments = path.split("/")
            for segment in segments:
                if not _SEGMENT_RE.match(segment):
                    raise ValueError(
                        f"Invalid property path segment '{segment}' in field '{field_name}'. "
                        "Each segment must be 'prefix:localName'."
                    )
        return v


class RDFMappingConfig(BaseModel):
    """Root configuration model for the RDF Mention Parser.

    Loaded once at startup from a YAML file.  Validates that every namespace
    prefix referenced in ``rdf_type`` values and field property paths is
    declared in ``namespaces``.
    """

    namespaces: dict[str, str]
    entity_types: dict[str, EntityTypeConfig]

    @field_validator("entity_types")
    @classmethod
    def entity_types_not_empty(
        cls, v: dict[str, "EntityTypeConfig"]
    ) -> dict[str, "EntityTypeConfig"]:
        if not v:
            raise ValueError("entity_types must not be empty")
        return v

    @model_validator(mode="after")
    def validate_prefix_consistency(self) -> "RDFMappingConfig":
        """Every prefix used in rdf_type values and field paths must be in namespaces."""
        declared = set(self.namespaces.keys())

        for type_key, config in self.entity_types.items():
            rdf_prefix = config.rdf_type.split(":")[0]
            if rdf_prefix not in declared:
                raise ValueError(
                    f"Prefix '{rdf_prefix}' used in rdf_type of '{type_key}' "
                    "is not declared in namespaces."
                )

            for field_name, path in config.fields.items():
                for segment in path.split("/"):
                    seg_prefix = segment.split(":")[0]
                    if seg_prefix not in declared:
                        raise ValueError(
                            f"Prefix '{seg_prefix}' used in field '{field_name}' "
                            f"of '{type_key}' is not declared in namespaces."
                        )

        return self

    def get_entity_type_config(self, name: str) -> EntityTypeConfig:
        """Return the EntityTypeConfig for the given short key name.

        Args:
            name: Short entity type key, e.g. ``ORGANISATION``.

        Raises:
            UnsupportedEntityTypeError: If no entry matches ``name``.
        """
        try:
            return self.entity_types[name]
        except KeyError as e:
            raise UnsupportedEntityTypeError(name) from e

    def resolve_entity_type(self, uri: str) -> EntityTypeConfig:
        """Return the EntityTypeConfig whose rdf_type expands to the given full URI.

        Args:
            uri: Full IRI, e.g. ``http://www.w3.org/ns/org#Organization``.

        Raises:
            UnsupportedEntityTypeError: If no configured entity type matches ``uri``.
        """
        for config in self.entity_types.values():
            prefix, local = config.rdf_type.split(":", 1)
            if self.namespaces[prefix] + local == uri:
                return config

        raise UnsupportedEntityTypeError(uri)
