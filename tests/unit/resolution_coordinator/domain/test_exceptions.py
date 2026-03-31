"""Unit tests for resolution_coordinator domain exceptions and config."""

import pytest

from ers.commons.services.exceptions import ApplicationError
from ers.resolution_coordinator.domain.exceptions import (
    CoordinatorException,
    EnginePublishFailedException,
    ParsingFailedException,
    ResolutionTimeoutException,
)

ALL_SIMPLE_EXCEPTIONS = [ResolutionTimeoutException]
ALL_CAUSE_EXCEPTIONS = [ParsingFailedException, EnginePublishFailedException]
ALL_EXCEPTIONS = ALL_SIMPLE_EXCEPTIONS + ALL_CAUSE_EXCEPTIONS


class TestExceptionInstantiation:
    @pytest.mark.parametrize("exc_class", ALL_SIMPLE_EXCEPTIONS)
    def test_instantiable_with_message(self, exc_class):
        exc = exc_class("something went wrong")
        assert exc is not None

    @pytest.mark.parametrize("exc_class", ALL_CAUSE_EXCEPTIONS)
    def test_cause_exceptions_instantiable_with_message_and_cause(self, exc_class):
        cause = ValueError("original error")
        exc = exc_class("something went wrong", cause)
        assert exc is not None

    @pytest.mark.parametrize("exc_class", ALL_SIMPLE_EXCEPTIONS)
    def test_inherits_from_coordinator_exception(self, exc_class):
        assert issubclass(exc_class, CoordinatorException)

    @pytest.mark.parametrize("exc_class", ALL_CAUSE_EXCEPTIONS)
    def test_cause_exceptions_inherit_from_coordinator_exception(self, exc_class):
        assert issubclass(exc_class, CoordinatorException)

    def test_coordinator_exception_inherits_from_application_error(self):
        assert issubclass(CoordinatorException, ApplicationError)

    @pytest.mark.parametrize("exc_class", ALL_SIMPLE_EXCEPTIONS)
    def test_str_includes_message(self, exc_class):
        msg = "detailed error description"
        exc = exc_class(msg)
        assert msg in str(exc)

    @pytest.mark.parametrize("exc_class", ALL_SIMPLE_EXCEPTIONS)
    def test_can_be_raised_and_caught(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("raised!")

    @pytest.mark.parametrize("exc_class", ALL_CAUSE_EXCEPTIONS)
    def test_cause_exceptions_can_be_raised_and_caught(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("raised!", RuntimeError("cause"))


class TestParsingFailedException:
    def test_stores_cause_attribute(self):
        original = ValueError("parse error")
        exc = ParsingFailedException("failed to parse", original)
        assert exc.cause is original

    def test_cause_is_not_re_raised(self):
        original = ValueError("parse error")
        exc = ParsingFailedException("failed", original)
        # cause is stored but not set as __cause__ automatically
        assert exc.__cause__ is None

    def test_message_accessible(self):
        exc = ParsingFailedException("parsing failed", ValueError("x"))
        assert exc.message == "parsing failed"


class TestEnginePublishFailedException:
    def test_stores_cause_attribute(self):
        original = ConnectionError("redis down")
        exc = EnginePublishFailedException("publish failed", original)
        assert exc.cause is original

    def test_cause_is_not_re_raised(self):
        original = ConnectionError("redis down")
        exc = EnginePublishFailedException("failed", original)
        assert exc.__cause__ is None

    def test_message_accessible(self):
        exc = EnginePublishFailedException("engine publish failed", ConnectionError("x"))
        assert exc.message == "engine publish failed"


class TestCoordinatorConfig:
    def test_single_request_budget_default(self):
        from ers import config

        assert config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET == 30.0

    def test_bulk_request_budget_default(self):
        from ers import config

        assert config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET == 120.0

    def test_single_budget_returns_float(self):
        from ers import config

        assert isinstance(config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET, float)

    def test_bulk_budget_returns_float(self):
        from ers import config

        assert isinstance(config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET, float)

    def test_single_budget_env_override(self, monkeypatch):
        monkeypatch.setenv("ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET", "60")
        from ers import ERSConfigResolver

        cfg = ERSConfigResolver()
        assert cfg.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET == 60.0

    def test_bulk_budget_env_override(self, monkeypatch):
        monkeypatch.setenv("ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET", "300")
        from ers import ERSConfigResolver

        cfg = ERSConfigResolver()
        assert cfg.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET == 300.0
