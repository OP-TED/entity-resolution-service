import json
from typing import cast

from dotenv import load_dotenv

from ers.commons.adapters.config_resolver import env_property

load_dotenv()


class CurationAppConfig:
    @env_property(default_value="Curation REST API")
    def APP_NAME(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="false")
    def DEBUG(self, config_value: str) -> bool:
        return config_value.lower() == "true"

    @env_property(default_value="/api/v1")
    def API_V1_PREFIX(self, config_value: str) -> str:
        return config_value

    @env_property(default_value='["*"]')
    def CORS_ORIGINS(self, config_value: str) -> list[str]:
        return cast(list[str], json.loads(config_value))


class JWTConfig:
    @env_property(default_value="change-me-in-production")
    def JWT_SECRET_KEY(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="HS256")
    def JWT_ALGORITHM(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="15")
    def ACCESS_TOKEN_EXPIRE_MINUTES(self, config_value: str) -> int:
        return int(config_value)

    @env_property(default_value="10080")
    def REFRESH_TOKEN_EXPIRE_MINUTES(self, config_value: str) -> int:
        return int(config_value)


class AdminConfig:
    @env_property(default_value="admin@ers.local")
    def ADMIN_EMAIL(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="changeme")
    def ADMIN_PASSWORD(self, config_value: str) -> str:
        return config_value


class MongoDBConfig:
    @env_property(default_value="mongodb://username:password@localhost:27017")
    def MONGO_URI(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="ers")
    def MONGO_DATABASE_NAME(self, config_value: str) -> str:
        return config_value


class RDFMentionParserConfig:
    @env_property(default_value="1048576")
    def ERS_PARSER_MAX_CONTENT_LENGTH(self, config_value: str) -> int:
        return int(config_value)

    @env_property(default_value="tests/test_data/sample_rdf_mapping.yaml")
    def RDF_MENTION_CONFIG_FILE(self, config_value: str) -> str:
        return config_value


class ERSRestApiConfig:
    @env_property(default_value="ERS REST API")
    def ERS_API_NAME(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="/api/v1")
    def ERS_API_PREFIX(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="8001")
    def ERS_API_PORT(self, config_value: str) -> int:
        return int(config_value)


class EREConfig:
    @env_property(default_value="1000")
    def REFRESH_BULK_MAX_LIMIT(self, config_value: str) -> int:
        return int(config_value)


class RedisConfig:
    @env_property(default_value="localhost")
    def REDIS_HOST(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="6379")
    def REDIS_PORT(self, config_value: str) -> int:
        return int(config_value)

    @env_property(default_value="0")
    def REDIS_DB(self, config_value: str) -> int:
        return int(config_value)

    @env_property(default_value="changeme")
    def REDIS_PASSWORD(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="ere_requests")
    def ERE_REQUEST_CHANNEL(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="ere_responses")
    def ERE_RESPONSE_CHANNEL(self, config_value: str) -> str:
        return config_value


class DecisionStoreConfig:
    @env_property(default_value="5")
    def DECISION_STORE_MAX_CANDIDATES(self, config_value: str) -> int:
        value = int(config_value)
        if value < 1:
            raise ValueError(f"DECISION_STORE_MAX_CANDIDATES must be >= 1, got {value}")
        return value

    @env_property(default_value="250")
    def DECISION_STORE_DEFAULT_PAGE_SIZE(self, config_value: str) -> int:
        value = int(config_value)
        if value < 1:
            raise ValueError(f"DECISION_STORE_DEFAULT_PAGE_SIZE must be >= 1, got {value}")
        max_size = self.DECISION_STORE_MAX_PAGE_SIZE
        if value > max_size:
            raise ValueError(
                f"DECISION_STORE_DEFAULT_PAGE_SIZE ({value}) must be <= "
                f"DECISION_STORE_MAX_PAGE_SIZE ({max_size})"
            )
        return value

    @env_property(default_value="1000")
    def DECISION_STORE_MAX_PAGE_SIZE(self, config_value: str) -> int:
        value = int(config_value)
        if value < 1:
            raise ValueError(f"DECISION_STORE_MAX_PAGE_SIZE must be >= 1, got {value}")
        return value


class ObservabilityConfig:
    @env_property(default_value="false")
    def TRACING_ENABLED(self, config_value: str) -> bool:
        return config_value.lower() == "true"

    @env_property(default_value="entity-resolution-service")
    def OTEL_SERVICE_NAME(self, config_value: str) -> str:
        return config_value


class ResolutionCoordinatorConfig:
    @env_property(default_value="30")
    def ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET(self, config_value: str) -> float:
        """Maximum time budget for a single-mention resolution response.

        Also serves as the ERE wait window — if ERE does not respond within
        this budget, a provisional identifier is issued and returned to the client.
        """
        return float(config_value)

    @env_property(default_value="120")
    def ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET(self, config_value: str) -> float:
        """Maximum time budget for a bulk resolution response (all mentions combined).

        Each mention waits up to SINGLE_REQUEST_TIME_BUDGET for ERE internally.
        """
        return float(config_value)


class ERSConfigResolver(
    CurationAppConfig,
    JWTConfig,
    AdminConfig,
    MongoDBConfig,
    RedisConfig,
    RDFMentionParserConfig,
    ERSRestApiConfig,
    EREConfig,
    DecisionStoreConfig,
    ObservabilityConfig,
    ResolutionCoordinatorConfig,
):
    """Aggregates all ERS configuration.

    Values are resolved lazily from environment variables at property access time.
    The .env file (if present) is loaded once at module import via load_dotenv().
    Environment variables already set in the process take precedence over .env values.
    """


config = ERSConfigResolver()
"""Module-level singleton. Import as ``from ers import config``."""
