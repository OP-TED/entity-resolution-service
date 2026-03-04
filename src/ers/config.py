from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Entity Resolution Service"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default=["*"])

    sso_enabled: bool = False
    sso_issuer_url: str = ""
    sso_client_id: str = ""

    curation_confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Decisions with confidence below this threshold appear in curation worklist",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database_name: str = "ers"


def get_settings() -> Settings:
    return Settings()
