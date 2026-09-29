
from ers.commons.adapters.config_resolver import (
    DefaultConfigResolver,
    EnvConfigResolver,
    env_property,
)


class TestEnvConfigResolver:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "hello")
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("MY_KEY") == "hello"

    def test_returns_default_when_missing(self):
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("__NONEXISTENT__", "fallback") == "fallback"

    def test_returns_none_when_missing_no_default(self):
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("__NONEXISTENT__") is None


class TestDefaultConfigResolver:
    def test_returns_default_ignoring_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from_env")
        resolver = DefaultConfigResolver()
        assert resolver.concrete_config_resolve("MY_KEY", "my_default") == "my_default"

    def test_returns_none_when_no_default(self):
        resolver = DefaultConfigResolver()
        assert resolver.concrete_config_resolve("ANY_KEY") is None


class TestEnvProperty:
    def test_method_name_is_the_env_key(self, monkeypatch):
        monkeypatch.setenv("MY_SETTING", "42")

        class SampleConfig:
            @env_property()
            def MY_SETTING(self, config_value: str) -> int:
                return int(config_value)

        assert SampleConfig().MY_SETTING == 42

    def test_default_value_used_when_env_absent(self):
        class SampleConfig:
            @env_property(default_value="99")
            def ABSENT_KEY(self, config_value: str) -> int:
                return int(config_value)

        assert SampleConfig().ABSENT_KEY == 99

    def test_custom_resolver_class_is_used(self, monkeypatch):
        monkeypatch.setenv("OVERRIDE_ME", "from_env")

        class SampleConfig:
            @env_property(config_resolver_class=DefaultConfigResolver, default_value="from_default")
            def OVERRIDE_ME(self, config_value: str) -> str:
                return config_value

        # DefaultConfigResolver ignores env; returns default
        assert SampleConfig().OVERRIDE_ME == "from_default"

    def test_env_property_is_a_property(self):
        class SampleConfig:
            @env_property(default_value="x")
            def SOME_KEY(self, config_value: str) -> str:
                return config_value

        assert isinstance(SampleConfig.__dict__["SOME_KEY"], property)

    def test_env_property_forwards_docstring(self):
        class SampleConfig:
            @env_property(default_value="x")
            def DOCUMENTED_KEY(self, config_value: str) -> str:
                """This is the docstring."""
                return config_value

        assert SampleConfig.__dict__["DOCUMENTED_KEY"].__doc__ == "This is the docstring."


class TestConfigResolveStackMethod:
    def test_config_resolve_uses_caller_name_as_key(self, monkeypatch):
        monkeypatch.setenv("MY_STACK_KEY", "stack_value")
        resolver = EnvConfigResolver()

        def MY_STACK_KEY():
            return resolver.config_resolve()

        assert MY_STACK_KEY() == "stack_value"
