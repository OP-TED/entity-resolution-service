"""Unit tests for OutcomeValidationError and TriadNotFoundError."""
import pytest
from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError
from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)


def make_identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id="S", request_id="R", entity_type="T")


class TestOutcomeValidationError:
    def test_is_application_error(self):
        assert issubclass(OutcomeValidationError, ApplicationError)

    def test_detail_attribute_set(self):
        err = OutcomeValidationError("null timestamp")
        assert err.detail == "null timestamp"

    def test_message_equals_detail(self):
        err = OutcomeValidationError("empty candidates")
        assert str(err) == "empty candidates"

    def test_can_be_raised_and_caught(self):
        with pytest.raises(OutcomeValidationError) as exc_info:
            raise OutcomeValidationError("test detail")
        assert exc_info.value.detail == "test detail"


class TestTriadNotFoundError:
    def test_is_application_error(self):
        assert issubclass(TriadNotFoundError, ApplicationError)

    def test_identifier_attribute_set(self):
        identifier = make_identifier()
        err = TriadNotFoundError(identifier)
        assert err.identifier is identifier

    def test_message_includes_triad_fields(self):
        identifier = make_identifier()
        err = TriadNotFoundError(identifier)
        msg = str(err)
        assert "S" in msg
        assert "R" in msg
        assert "T" in msg

    def test_can_be_raised_and_caught(self):
        identifier = make_identifier()
        with pytest.raises(TriadNotFoundError) as exc_info:
            raise TriadNotFoundError(identifier)
        assert exc_info.value.identifier == identifier
