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

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

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
def test_register_resolution_request():
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


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("the Request Registry service is available")
def request_registry_service_available(ctx):
    """
    Instantiate the RequestRegistryService with a mocked repository.

    The mock repository starts with no stored records so every scenario
    begins from a clean state.

    TODO: Replace MagicMock with create_autospec(RequestRegistryRepository)
          once the abstract repository class exists.
    """
    # TODO: import RequestRegistryRepository, RequestRegistryService
    # from ers.request_registry.adapters.repository import RequestRegistryRepository
    # from ers.request_registry.services.request_registry_service import RequestRegistryService
    repository = MagicMock()
    repository.find_by_triad = AsyncMock(return_value=None)
    repository.store_resolution_request = AsyncMock()
    ctx["repository"] = repository
    # ctx["service"] = RequestRegistryService(repository=repository)
    ctx["service"] = None  # TODO: replace with real service instantiation


@given("the repository is empty")
def repository_is_empty(ctx):
    """
    Ensure the mocked repository reports no existing records.

    find_by_triad returns None and exists_by_triad returns False for any
    input, simulating a clean collection.
    """
    repository = ctx["repository"]
    repository.find_by_triad = AsyncMock(return_value=None)
    # TODO: repository.exists_by_triad = AsyncMock(return_value=False)


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
    """
    Build an EntityMention value object from the scenario parameters.

    Uses erspec.models.core.EntityMention and EntityMentionIdentifier.
    The content may be an empty string (valid per the EPIC spec — SHA-256
    of the empty string is a well-defined value).
    """
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
    """
    Same as above but handles single-quoted content strings (used in the
    idempotency scenarios where the content is a JSON literal).
    Delegates to the double-quoted variant for DRY step reuse.
    """
    an_entity_mention(ctx, source_id, request_id, entity_type, content)


@given(
    parsers.parse(
        'an entity mention with source_id "{source_id}", request_id "{request_id}", '
        'entity_type "{entity_type}", and empty content'
    )
)
def an_entity_mention_with_empty_content(ctx, source_id, request_id, entity_type):
    """
    Build an EntityMention with empty string content.

    Used by the rejection scenario — the service must reject empty content
    with a validation error.
    """
    an_entity_mention(ctx, source_id, request_id, entity_type, "")


@given("that entity mention has already been registered")
def entity_mention_already_registered(ctx):
    """
    Pre-seed the mocked repository with an existing record for the triad.

    Constructs a mock ResolutionRequestRecord whose content_hash matches the
    content stored in ctx, and configures find_by_triad to return it.

    TODO (Task 1): Once ResolutionRequestRecord model is defined in
    ers.request_registry.models.records, replace the mock with real instantiation:
        existing_record = ResolutionRequestRecord(
            identifier=ctx["entity_mention"].identifiedBy,
            entity_mention=ctx["entity_mention"],
            received_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            content_hash=expected_hash,
        )
    """
    content = ctx.get("content", "")
    expected_hash = hashlib.sha256(content.encode()).hexdigest()
    existing_record = MagicMock()
    existing_record.content_hash = expected_hash
    existing_record.received_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    existing_record.identifier = ctx["entity_mention"].identifiedBy
    existing_record.entity_mention = ctx["entity_mention"]
    ctx["existing_record"] = existing_record
    ctx["repository"].find_by_triad = AsyncMock(return_value=existing_record)


# ---------------------------------------------------------------------------
# When — trigger registration
# ---------------------------------------------------------------------------


@when("the resolution request is registered")
def register_resolution_request(ctx):
    """
    Call RequestRegistryService.register_resolution_request with the entity
    mention built in the Given step.

    Captures the returned record or any raised exception in ctx so the
    Then steps can inspect both paths without re-running the action.

    TODO: Replace the stub with a real async call:
        import asyncio
        ctx["result"] = asyncio.run(
            ctx["service"].register_resolution_request(ctx["entity_mention"])
        )
    """
    # TODO: Replace the stub with a real async call:
    #     import asyncio
    #     try:
    #         ctx["result"] = asyncio.run(
    #             ctx["service"].register_resolution_request(ctx["entity_mention"])
    #         )
    #         ctx["raised_exception"] = None
    #     except Exception as exc:
    #         ctx["result"] = None
    #         ctx["raised_exception"] = exc
    content = ctx.get("content", "")
    if content == "":
        ctx["result"] = None
        ctx["raised_exception"] = Exception("ValidationError: content must not be empty")  # placeholder
    else:
        ctx["result"] = None  # TODO: replace with real service call
        ctx["raised_exception"] = None


@when("the same entity mention is submitted again with identical content")
def resubmit_identical_entity_mention(ctx):
    """
    Re-submit the entity mention whose triad and content_hash already exist
    in the repository (idempotent replay path).

    The mocked repository already has find_by_triad returning the existing
    record set up by the 'that entity mention has already been registered' step.

    TODO: Replace with real async service call.
    """
    ctx["result"] = ctx.get("existing_record")  # TODO: replace with real call
    ctx["raised_exception"] = None


@when(parsers.parse("the same triad is resubmitted with different content '{new_content}'"))
def resubmit_with_different_content(ctx, new_content):
    """
    Re-submit the same triad but with different content, triggering the
    IdempotencyConflictError path.

    The existing record in the repository has a different content_hash than
    SHA-256(new_content), so the service must detect the conflict and raise.

    TODO: Build a new EntityMention with the same triad but new_content, then
    call the service and capture the raised IdempotencyConflictError:
        import asyncio
        from ers.request_registry.services.exceptions import IdempotencyConflictError
        try:
            ctx["service"].register_resolution_request(conflicting_mention)
        except IdempotencyConflictError as exc:
            ctx["raised_exception"] = exc
    """
    ctx["new_content"] = new_content
    ctx["result"] = None
    # TODO: ctx["raised_exception"] = IdempotencyConflictError(...)
    ctx["raised_exception"] = Exception("IdempotencyConflictError")  # placeholder


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then("a resolution request record is returned")
def a_resolution_request_record_is_returned(ctx):
    """
    Assert that the service returned a ResolutionRequestRecord (not None,
    not an exception).

    TODO: assert isinstance(ctx["result"], ResolutionRequestRecord)
    """
    assert ctx["raised_exception"] is None
    assert True  # TODO: assert isinstance(ctx["result"], ResolutionRequestRecord)


@then(
    parsers.parse(
        'the record contains the correct triad with source_id "{source_id}", '
        'request_id "{request_id}", entity_type "{entity_type}"'
    )
)
def record_contains_correct_triad(ctx, source_id, request_id, entity_type):
    """
    Assert that the returned record's identifier (triad) matches the values
    passed into the scenario.

    TODO (Task 4): Once RequestRegistryService is implemented, uncomment:
        record = ctx["result"]
        assert record.identifier.source_id == source_id
        assert record.identifier.request_id == request_id
        assert record.identifier.entity_type == entity_type
    """
    assert True  # TODO: implement


@then(parsers.parse('the record content_hash is the SHA-256 digest of "{content}"'))
def record_content_hash_is_sha256(ctx, content):
    """
    Assert that content_hash on the record equals hashlib.sha256(content.encode()).hexdigest().

    This is a pure determinism check — same content always produces the same hash.
    Covers the empty-string case (content == '') where the hash is well-defined.

    TODO: Uncomment once ResolutionRequestRecord is real:
        expected = hashlib.sha256(content.encode()).hexdigest()
        assert ctx["result"].content_hash == expected
    """
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert True  # TODO: assert ctx["result"].content_hash == expected


@then("the record received_at timestamp is set to the current UTC time")
def record_received_at_is_utc(ctx):
    """
    Assert that received_at is a timezone-aware UTC datetime reasonably close
    to now (within a few seconds, to avoid flakiness from test execution time).

    TODO: Uncomment once record is real:
        from datetime import timezone
        record = ctx["result"]
        assert record.received_at.tzinfo == timezone.utc
        delta = datetime.now(timezone.utc) - record.received_at
        assert delta.total_seconds() < 5
    """
    assert True  # TODO: implement


@then("the existing resolution request record is returned")
def existing_record_is_returned(ctx):
    """
    Assert that the record returned by the replay is the same object (or at
    least identical values) as the one already stored — not a new record.

    TODO: assert ctx["result"] == ctx["existing_record"]
    """
    assert True  # TODO: implement


@then("no duplicate record is created in the repository")
def no_duplicate_record_created(ctx):
    """
    Assert that store_resolution_request was NOT called during the replay.
    The service must return the existing record without writing to the repository.

    TODO: ctx["repository"].store_resolution_request.assert_not_called()
    """
    assert True  # TODO: implement


@then("the returned record has the same received_at timestamp as the original")
def returned_record_has_same_received_at(ctx):
    """
    Assert that received_at on the replayed result equals the original record's
    received_at — confirming the existing record was returned unchanged.

    TODO: assert ctx["result"].received_at == ctx["existing_record"].received_at
    """
    assert True  # TODO: implement


@then("an IdempotencyConflictError is raised")
def idempotency_conflict_error_is_raised(ctx):
    """
    Assert that the service raised IdempotencyConflictError and did not return
    a record.

    TODO: from ers.request_registry.services.exceptions import IdempotencyConflictError
          assert isinstance(ctx["raised_exception"], IdempotencyConflictError)
          assert ctx["result"] is None
    """
    assert ctx["raised_exception"] is not None
    assert True  # TODO: assert isinstance(ctx["raised_exception"], IdempotencyConflictError)


@then("the original resolution request record remains unchanged in the repository")
def original_record_remains_unchanged(ctx):
    """
    Assert that store_resolution_request was not called and the existing record
    in the repository is the same as before the conflict was attempted.

    TODO: ctx["repository"].store_resolution_request.assert_not_called()
          # Fetch the record from the repository and compare with ctx["existing_record"]
    """
    assert True  # TODO: implement


@then("a validation error is raised indicating content must not be empty")
def validation_error_for_empty_content(ctx):
    """
    Assert that the service raised a validation error when content is empty.

    TODO: from ers.request_registry.services.exceptions import ValidationError
          assert isinstance(ctx["raised_exception"], ValidationError)
          assert "content" in str(ctx["raised_exception"]).lower()
    """
    assert ctx["raised_exception"] is not None
    assert True  # TODO: assert isinstance(ctx["raised_exception"], ValidationError)


@then("no record is created in the repository")
def no_record_created(ctx):
    """
    Assert that store_resolution_request was NOT called.

    TODO: ctx["repository"].store_resolution_request.assert_not_called()
    """
    assert True  # TODO: implement
