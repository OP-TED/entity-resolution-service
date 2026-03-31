import json

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
        return json.loads(config_value)


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


class CurationConfig:
    @env_property(default_value="0.85")
    def CURATION_CONFIDENCE_THRESHOLD(self, config_value: str) -> float:
        return float(config_value)


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

    @env_property(default_value="rdf_mention_config.yaml")
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

    @env_property(default_value="false")
    def USE_MOCK_SERVICES(self, config_value: str) -> bool:
        """Enable factory-generated mock responses (temporary dev)."""
        return config_value.lower() == "true"


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

    @env_property(default_value="ere_requests")
    def ERE_REQUEST_CHANNEL(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="ere_responses")
    def ERE_RESPONSE_CHANNEL(self, config_value: str) -> str:
        return config_value


class ObservabilityConfig:
    @env_property(default_value="false")
    def TRACING_ENABLED(self, config_value: str) -> bool:
        return config_value.lower() == "true"

    @env_property(default_value="entity-resolution-service")
    def OTEL_SERVICE_NAME(self, config_value: str) -> str:
        return config_value


class ERSConfigResolver(
    CurationAppConfig,
    JWTConfig,
    AdminConfig,
    CurationConfig,
    MongoDBConfig,
    RedisConfig,
    RDFMentionParserConfig,
    ERSRestApiConfig,
    EREConfig,
    ObservabilityConfig,
):
    """Aggregates all ERS configuration.

    Values are resolved lazily from environment variables at property access time.
    The .env file (if present) is loaded once at module import via load_dotenv().
    Environment variables already set in the process take precedence over .env values.
    """


config = ERSConfigResolver()
"""Module-level singleton. Import as ``from ers import config``."""
