import pytest
from ers.commons.services.exceptions import ApplicationError, ServiceUnavailableError


class TestServiceUnavailableError:
    def test_is_application_error(self):
        exc = ServiceUnavailableError("MongoDB is down")
        assert isinstance(exc, ApplicationError)

    def test_message_preserved(self):
        exc = ServiceUnavailableError("Redis unreachable")
        assert exc.message == "Redis unreachable"

    def test_str_is_message(self):
        exc = ServiceUnavailableError("timeout")
        assert str(exc) == "timeout"
