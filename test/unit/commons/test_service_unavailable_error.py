from ers.commons.services.exceptions import ApplicationError, ServiceUnavailableError


class TestServiceUnavailableError:
    def test_is_application_error(self):
        exc = ServiceUnavailableError("mongodb")
        assert isinstance(exc, ApplicationError)

    def test_service_name_field_required_and_exposed(self):
        """B3: ServiceUnavailableError must carry a structured ``service_name``
        field so logs/dashboards/SLO alerts can distinguish which backend
        ('mongodb' / 'redis' / 'channel') is unhealthy."""
        exc = ServiceUnavailableError("redis")
        assert exc.service_name == "redis"

    def test_optional_detail_preserved(self):
        exc = ServiceUnavailableError("mongodb", "connection refused")
        assert exc.service_name == "mongodb"
        assert exc.detail == "connection refused"

    def test_message_includes_service_name(self):
        exc = ServiceUnavailableError("redis", "timeout after 5s")
        assert "redis" in exc.message
        assert "timeout after 5s" in exc.message

    def test_message_without_detail_still_names_service(self):
        exc = ServiceUnavailableError("channel")
        assert "channel" in exc.message

    def test_str_is_message(self):
        exc = ServiceUnavailableError("mongodb", "down")
        assert str(exc) == exc.message
