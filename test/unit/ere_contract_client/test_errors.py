"""Unit tests for ere_contract_client domain errors."""

import pytest

from ers.commons.domain.exceptions import DomainError
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    DeserializationError,
    EREContractError,
    InvalidRequestError,
    RedisConnectionError,
    SerializationError,
)

ALL_ERROR_CLASSES = [
    InvalidRequestError,
    SerializationError,
    DeserializationError,
    ChannelUnavailableError,
    RedisConnectionError,
]


class TestErrorInstantiation:
    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_instantiable_with_message(self, error_class):
        err = error_class("something went wrong")
        assert err is not None

    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_inherits_from_domain_error(self, error_class):
        err = error_class("msg")
        assert isinstance(err, DomainError)

    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_inherits_from_ere_contract_error(self, error_class):
        err = error_class("msg")
        assert isinstance(err, EREContractError)

    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_str_includes_message(self, error_class):
        msg = "detailed error description"
        err = error_class(msg)
        assert msg in str(err)

    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_is_exception(self, error_class):
        err = error_class("test")
        assert isinstance(err, Exception)

    @pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
    def test_can_be_raised_and_caught(self, error_class):
        with pytest.raises(error_class):
            raise error_class("raised!")
