"""Unit tests for AsyncOutcomeListener interface."""
from abc import ABC

from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener


class TestAsyncOutcomeListenerInterface:
    def test_is_abstract_base_class(self):
        assert issubclass(AsyncOutcomeListener, ABC)

    def test_cannot_be_instantiated_directly(self):
        import pytest
        with pytest.raises(TypeError):
            AsyncOutcomeListener()  # type: ignore

    def test_consume_is_abstract(self):
        assert getattr(AsyncOutcomeListener.consume, "__isabstractmethod__", False)
