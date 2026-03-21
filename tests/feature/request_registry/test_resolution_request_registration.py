"""
Step definitions for: resolution_request_registration.feature

Feature: Resolution Request Registration
  Covers four behaviours:
    1. Registering a new entity mention produces a ResolutionRequestRecord with the
       correct triad, content_hash (SHA-256), and received_at timestamp.
    2. Replaying an identical triad+content returns the existing record (idempotent).
    3. Replaying the same triad with different content raises IdempotencyConflictError.
    4. Submitting empty content is rejected with a validation error.

  These steps call the RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import create_autospec, patch

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.rdf_mention_parser.domain.rdf_mapping_config import EntityTypeConfig, RDFMappingConfig
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.exceptions import IdempotencyConflictError
from ers.request_registry.services.request_registry_service import RequestRegistryService

# ---------------------------------------------------------------------------
# Scenario bindings — link each scenario title to its .feature file.
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "request_registry"
    / "resolution_request_registration.feature"
)


@scenario(FEATURE_FILE, "Register a resolution request")
def test_register_resolution_request(mock_parse_entity_mention):
    """Bind the 'Register a resolution request' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Idempotent replay of an identical request")
def test_idempotent_replay():
    """Bind the 'Idempotent replay of an identical request' scenario."""
    pass


@scenario(FEATURE_FILE, "Reject idempotency conflict — same triad, different content")
def test_reject_idempotency_conflict():
    """Bind the 'Reject idempotency conflict' scenario."""
    pass


@scenario(FEATURE_FILE, "Reject a resolution request with empty content")
def test_reject_resolution_request_with_empty_content():
    """Bind the 'Reject a resolution request with empty content' scenario."""
    pass


# ---------------------------------------------------------------------------
# Shared context container
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


@pytest.fixture
def rdf_config() -> RDFMappingConfig:
    return RDFMappingConfig(
        namespaces={"ex": "http://example.org/"},
        entity_types={
            "organisation": EntityTypeConfig(
                rdf_type="ex:Organization",
                fields={"name": "ex:name"},
            )
        },
    )


@pytest.fixture
def mock_parse_entity_mention():
    with patch(
        "ers.request_registry.services.request_registry_service.parse_entity_mention",
        return_value={"name": "Acme Corp"},
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("the Request Registry service is available")
def request_registry_service_available(ctx, rdf_config):
    """Instantiate the RequestRegistryService with mocked repositories and a real hasher."""
    resolution_repo = create_autospec(MongoResolutionRequestRepository, instance=True)
    lookup_repo = create_autospec(MongoLookupStateRepository, instance=True)
    hasher = SHA256ContentHasher()

    service = RequestRegistryService(
        resolution_repo=resolution_repo,
        lookup_repo=lookup_repo,
        hasher=hasher,
        rdf_config=rdf_config,
    )

    ctx["resolution_repo"] = resolution_repo
    ctx["lookup_repo"] = lookup_repo
    ctx["hasher"] = hasher
    ctx["service"] = service


@given("the repository is empty")
def repository_is_empty(ctx):
    """Ensure the mocked repository reports no existing records."""
    ctx["resolution_repo"].find_by_triad.return_value = None


# ---------------------------------------------------------------------------
# Given — build entity mention
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'an entity mention with source_id "{source_id}", request_id "{request_id}", '
        'entity_type "{entity_type}", and content "{content}"'
    )
)
def an_entity_mention(ctx, source_id, request_id, entity_type, content):
    """Build an EntityMention value object from the scenario parameters."""
    identifier = EntityMentionIdentifier(
        source_id=source_id,
        request_id=request_id,
        entity_type=entity_type,
    )
    entity_mention = EntityMention(
        identifiedBy=identifier,
        content=content,
        content_type="application/ld+json",
    )
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["content"] = content
    ctx["entity_mention"] = entity_mention


@given(
    parsers.parse(
        'an entity mention with source_id "{source_id}", request_id "{request_id}", '
        "entity_type \"{entity_type}\", and content '{content}'"
    )
)
def an_entity_mention_single_quoted(ctx, source_id, request_id, entity_type, content):
    """Handle single-quoted content strings (used in idempotency scenarios)."""
    an_entity_mention(ctx, source_id, request_id, entity_type, content)


@given(
    parsers.parse(
        'an entity mention with source_id "{source_id}", request_id "{request_id}", '
        'entity_type "{entity_type}", and empty content'
    )
)
def an_entity_mention_with_empty_content(ctx, source_id, request_id, entity_type):
    """Build an EntityMention with empty string content."""
    an_entity_mention(ctx, source_id, request_id, entity_type, "")


@given("that entity mention has already been registered")
def entity_mention_already_registered(ctx):
    """Pre-seed the mocked repository with an existing record for the triad."""
    content = ctx.get("content", "")
    hasher = ctx["hasher"]
    expected_hash = hasher.hash(content)
    mention = ctx["entity_mention"]

    existing_record = ResolutionRequestRecord(
        **mention.model_dump(),
        content_hash=expected_hash,
        received_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    )
    ctx["existing_record"] = existing_record
    ctx["resolution_repo"].find_by_triad.return_value = existing_record


# ---------------------------------------------------------------------------
# When — trigger registration
# ---------------------------------------------------------------------------


@when("the resolution request is registered")
def register_resolution_request(ctx):
    """Call RequestRegistryService.register_resolution_request."""
    ctx["resolution_repo"].store.side_effect = lambda r: r

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_resolution_request(ctx["entity_mention"])
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("the same entity mention is submitted again with identical content")
def resubmit_identical_entity_mention(ctx):
    """Re-submit the entity mention (idempotent replay path)."""
    ctx["resolution_repo"].store.side_effect = lambda r: r

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_resolution_request(ctx["entity_mention"])
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse("the same triad is resubmitted with different content '{new_content}'"))
def resubmit_with_different_content(ctx, new_content):
    """Re-submit the same triad with different content (conflict path)."""
    conflicting_mention = EntityMention(
        identifiedBy=ctx["entity_mention"].identifiedBy,
        content=new_content,
        content_type="application/ld+json",
    )
    ctx["new_content"] = new_content

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_resolution_request(conflicting_mention)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then("a resolution request record is returned")
def a_resolution_request_record_is_returned(ctx):
    """Assert that the service returned a ResolutionRequestRecord."""
    assert ctx["raised_exception"] is None, (
        f"Expected a record but got exception: {ctx['raised_exception']}"
    )
    assert isinstance(ctx["result"], ResolutionRequestRecord), (
        f"Expected ResolutionRequestRecord, got {type(ctx['result'])}"
    )


@then(
    parsers.parse(
        'the record contains the correct triad with source_id "{source_id}", '
        'request_id "{request_id}", entity_type "{entity_type}"'
    )
)
def record_contains_correct_triad(ctx, source_id, request_id, entity_type):
    """Assert that the returned record's identifier matches the scenario values."""
    record = ctx["result"]
    assert record.identifiedBy.source_id == source_id
    assert record.identifiedBy.request_id == request_id
    assert record.identifiedBy.entity_type == entity_type


@then(parsers.parse('the record content_hash is the SHA-256 digest of "{content}"'))
def record_content_hash_is_sha256(ctx, content):
    """Assert that content_hash equals hashlib.sha256(content.encode()).hexdigest()."""
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert ctx["result"].content_hash == expected


@then("the record received_at timestamp is set to the current UTC time")
def record_received_at_is_utc(ctx):
    """Assert that received_at is a timezone-aware UTC datetime within 2 seconds of now."""
    record = ctx["result"]
    assert record.received_at.tzinfo is not None
    delta = abs(datetime.now(UTC) - record.received_at)
    assert delta < timedelta(seconds=2), (
        f"received_at {record.received_at} is more than 2 seconds away from now"
    )


@then("the existing resolution request record is returned")
def existing_record_is_returned(ctx):
    """Assert that the record returned by the replay is identical to the pre-existing one."""
    assert ctx["result"] is ctx["existing_record"], (
        "Expected the existing record to be returned unchanged, but got a different object"
    )


@then("no duplicate record is created in the repository")
def no_duplicate_record_created(ctx):
    """Assert that store was NOT called during the idempotent replay."""
    ctx["resolution_repo"].store.assert_not_called()


@then("the returned record has the same received_at timestamp as the original")
def returned_record_has_same_received_at(ctx):
    """Assert that received_at on the replayed result equals the original record's received_at."""
    assert ctx["result"].received_at == ctx["existing_record"].received_at


@then("an IdempotencyConflictError is raised")
def idempotency_conflict_error_is_raised(ctx):
    """Assert that the service raised IdempotencyConflictError."""
    assert ctx["raised_exception"] is not None, "Expected IdempotencyConflictError but no exception was raised"
    assert isinstance(ctx["raised_exception"], IdempotencyConflictError), (
        f"Expected IdempotencyConflictError, got {type(ctx['raised_exception'])}"
    )
    assert ctx["result"] is None


@then("the original resolution request record remains unchanged in the repository")
def original_record_remains_unchanged(ctx):
    """Assert that store was not called and the existing record is unchanged."""
    ctx["resolution_repo"].store.assert_not_called()


@then("a validation error is raised indicating content must not be empty")
def validation_error_for_empty_content(ctx):
    """Assert that the service raised a ValueError when content is empty."""
    assert ctx["raised_exception"] is not None, "Expected a ValueError but no exception was raised"
    assert isinstance(ctx["raised_exception"], ValueError), (
        f"Expected ValueError, got {type(ctx['raised_exception'])}"
    )
    assert "empty" in str(ctx["raised_exception"]).lower(), (
        f"Expected 'empty' in error message, got: {ctx['raised_exception']}"
    )


@then("no record is created in the repository")
def no_record_created(ctx):
    """Assert that store was NOT called when content is empty."""
    ctx["resolution_repo"].store.assert_not_called()
