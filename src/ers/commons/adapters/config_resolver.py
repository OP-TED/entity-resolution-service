import inspect
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class ConfigResolverABC(ABC):
    """Abstract base for configuration resolution strategies."""

    def config_resolve(self, default_value: str | None = None) -> str | None:
        """Resolve config using the caller method name as the key."""
        config_name = inspect.stack()[1][3]
        return self.concrete_config_resolve(config_name, default_value)

    @abstractmethod
    def concrete_config_resolve(
        self, config_name: str, default_value: str | None = None
    ) -> str | None:
        """Resolve a named config value, returning default_value if not found."""
        raise NotImplementedError


class EnvConfigResolver(ConfigResolverABC):
    """Resolves config from environment variables."""

    def concrete_config_resolve(
        self, config_name: str, default_value: str | None = None
    ) -> str | None:
        value = os.environ.get(config_name, default_value)
        logger.debug("[ENV] %s resolved (has_value=%s)", config_name, value is not None)
        return value


class DefaultConfigResolver(ConfigResolverABC):
    """Returns only the supplied default — ignores environment variables.

    Useful in tests and as a terminal fallback in composite resolvers.
    """

    def concrete_config_resolve(
        self, config_name: str, default_value: str | None = None
    ) -> str | None:
        return default_value


def env_property(
    config_resolver_class: type[ConfigResolverABC] = EnvConfigResolver,
    default_value: str | None = None,
):
    """Decorator factory that turns a method into a config-backed property.

    The decorated method name becomes the environment variable key.
    The resolved string is passed as ``config_value``; the method body
    handles type coercion.

    Usage::

        class MyConfig:
            @env_property(default_value="5432")
            def DB_PORT(self, config_value: str) -> int:
                return int(config_value)
    """

    def decorator(func):
        @property
        def wrapper(self):
            resolver = config_resolver_class()
            config_value = resolver.concrete_config_resolve(func.__name__, default_value)
            return func(self, config_value)

        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
