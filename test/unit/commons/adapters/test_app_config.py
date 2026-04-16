import pytest

from ers import (
    AdminConfig,
    CurationAppConfig,
    JWTConfig,
    MongoDBConfig,
    ObservabilityConfig,
    RDFMentionParserConfig,
    config,
)


class TestAppConfig:
    def test_app_name_default(self, monkeypatch):
        monkeypatch.delenv("APP_NAME", raising=False)
        assert CurationAppConfig().APP_NAME == "Curation REST API"

    def test_debug_default_is_false(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        assert CurationAppConfig().DEBUG is False

    def test_debug_true_from_env(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        assert CurationAppConfig().DEBUG is True

    def test_cors_origins_default_is_list(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        assert CurationAppConfig().CORS_ORIGINS == ["*"]

    def test_cors_origins_from_env(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", '["https://a.com","https://b.com"]')
        assert CurationAppConfig().CORS_ORIGINS == ["https://a.com", "https://b.com"]


class TestJWTConfig:
    def test_algorithm_default(self, monkeypatch):
        monkeypatch.delenv("JWT_ALGORITHM", raising=False)
        assert JWTConfig().JWT_ALGORITHM == "HS256"

    def test_access_expire_minutes_is_int(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        assert isinstance(JWTConfig().ACCESS_TOKEN_EXPIRE_MINUTES, int)
        assert JWTConfig().ACCESS_TOKEN_EXPIRE_MINUTES == 15

    def test_jwt_secret_key_required(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            _ = JWTConfig().JWT_SECRET_KEY


class TestAdminConfig:
    def test_admin_email_required(self, monkeypatch):
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        with pytest.raises(ValueError, match="ADMIN_EMAIL"):
            _ = AdminConfig().ADMIN_EMAIL

    def test_admin_password_required(self, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
            _ = AdminConfig().ADMIN_PASSWORD

    def test_admin_password_from_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "supersecret")
        assert AdminConfig().ADMIN_PASSWORD == "supersecret"


class TestMongoDBConfig:
    def test_mongo_uri_default(self, monkeypatch):
        monkeypatch.delenv("MONGO_URI", raising=False)
        assert MongoDBConfig().MONGO_URI == "mongodb://username:password@localhost:27017"

    def test_mongo_database_name_from_env(self, monkeypatch):
        monkeypatch.setenv("MONGO_DATABASE_NAME", "mydb")
        assert MongoDBConfig().MONGO_DATABASE_NAME == "mydb"


class TestRDFMentionParserConfig:
    def test_max_content_length_default(self, monkeypatch):
        monkeypatch.delenv("ERS_PARSER_MAX_CONTENT_LENGTH", raising=False)
        assert RDFMentionParserConfig().ERS_PARSER_MAX_CONTENT_LENGTH == 1_048_576

    def test_max_content_length_from_env(self, monkeypatch):
        monkeypatch.setenv("ERS_PARSER_MAX_CONTENT_LENGTH", "2097152")
        assert RDFMentionParserConfig().ERS_PARSER_MAX_CONTENT_LENGTH == 2_097_152


class TestObservabilityConfig:
    def test_tracing_enabled_default_is_false(self, monkeypatch):
        monkeypatch.delenv("TRACING_ENABLED", raising=False)
        assert ObservabilityConfig().TRACING_ENABLED is False

    def test_tracing_enabled_true_from_env(self, monkeypatch):
        monkeypatch.setenv("TRACING_ENABLED", "true")
        assert ObservabilityConfig().TRACING_ENABLED is True


class TestAppConfigResolverSingleton:
    def test_config_singleton_has_all_keys(self):
        assert isinstance(config.APP_NAME, str)
        assert isinstance(config.DEBUG, bool)
        assert isinstance(config.CORS_ORIGINS, list)
        assert isinstance(config.JWT_SECRET_KEY, str)
        assert isinstance(config.JWT_ALGORITHM, str)
        assert isinstance(config.ADMIN_EMAIL, str)
        assert isinstance(config.ADMIN_PASSWORD, str)
        assert isinstance(config.MONGO_URI, str)
        assert isinstance(config.ERS_PARSER_MAX_CONTENT_LENGTH, int)
        assert isinstance(config.TRACING_ENABLED, bool)
