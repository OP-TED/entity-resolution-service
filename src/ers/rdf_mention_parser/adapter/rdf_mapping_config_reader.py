from pathlib import Path

import yaml

from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig


class RDFConfigReader:
    """Loads a ParserConfig from a YAML source.

    Supports two loading strategies:
    - ``from_string(yaml_text)``  — parse from an in-memory YAML string
    - ``from_file(path)``         — parse from an explicit file path
    """

    @staticmethod
    def from_string(yaml_text: str) -> RDFMappingConfig:
        """Parse and validate a ParserConfig from a YAML string.

        Args:
            yaml_text: Raw YAML content.

        Returns:
            A validated ParserConfig instance.

        Raises:
            pydantic.ValidationError: If the YAML content fails validation.
            yaml.YAMLError: If the text is not valid YAML.
        """
        data = yaml.safe_load(yaml_text)
        return RDFMappingConfig(**data)

    @staticmethod
    def from_file(path: Path | str) -> RDFMappingConfig:
        """Parse and validate a ParserConfig from a YAML file on disk.

        Args:
            path: Filesystem path to the YAML config file.

        Returns:
            A validated ParserConfig instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            pydantic.ValidationError: If the file content fails validation.
            yaml.YAMLError: If the file is not valid YAML.
        """
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"RDF config file not found: {resolved}")
        return RDFConfigReader.from_string(resolved.read_text(encoding="utf-8"))

