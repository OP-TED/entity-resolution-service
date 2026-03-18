import os
from pathlib import Path

import yaml

from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "resources" / "rdf_mapping.yaml"
_ENV_VAR = "ERS_PARSER_CONFIG_PATH"


class RDFConfigReader:
    """Loads a ParserConfig from a YAML source.

    Supports three loading strategies (in order of call-site preference):
    - ``from_string(yaml_text)``  — parse from an in-memory YAML string
    - ``from_file(path)``         — parse from an explicit file path
    - ``from_env_or_default()``   — resolve path from ``ERS_PARSER_CONFIG_PATH``
                                    env var, falling back to the bundled default
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

    @staticmethod
    def from_env_or_default() -> RDFMappingConfig:
        """Load ParserConfig using ``ERS_PARSER_CONFIG_PATH`` env var or bundled default.

        Returns:
            A validated ParserConfig instance.

        Raises:
            FileNotFoundError: If the resolved path does not exist.
            pydantic.ValidationError: If the config content fails validation.
        """
        config_path = Path(os.environ.get(_ENV_VAR, _DEFAULT_CONFIG_PATH))
        return RDFConfigReader.from_file(config_path)
