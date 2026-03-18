Feature: Resolution Request Registration
  As a system that receives entity mentions from source systems,
  I want to register each mention as an immutable resolution request record,
  So that the triad (source_id, request_id, entity_type) is durably stored
  with a content hash, enabling idempotent replay and conflict detection.

  Background:
    Given the Request Registry service is available
    And the repository is empty

  Scenario Outline: Register a resolution request
    Given an entity mention with source_id "<source_id>", request_id "<request_id>", entity_type "<entity_type>", and content "<content>"
    When the resolution request is registered
    Then a resolution request record is returned
    And the record contains the correct triad with source_id "<source_id>", request_id "<request_id>", entity_type "<entity_type>"
    And the record content_hash is the SHA-256 digest of "<content>"
    And the record received_at timestamp is set to the current UTC time

    Examples:
      | source_id        | request_id | entity_type  | content                                                                 |
      | source_system_b  | req_002    | organization | {"name": "Acme Corp", "registration_number": "BE0123456789"}           |
      | source_system_b  | req_004    | organization | {"name": "Société Générale 株式会社 — ©2024", "flag": "🇫🇷"}           |

  Scenario: Register a resolution request with empty content
    Given an entity mention with source_id "source_system_a", request_id "req_003", entity_type "person", and empty content
    When the resolution request is registered
    Then a resolution request record is returned
    And the record content_hash is the SHA-256 digest of the empty string
    And the record received_at timestamp is set to the current UTC time

  Scenario: Idempotent replay of an identical request
    Given an entity mention with source_id "source_system_a", request_id "req_001", entity_type "person", and content '{"name": "Alice Dupont"}'
    And that entity mention has already been registered
    When the same entity mention is submitted again with identical content
    Then the existing resolution request record is returned
    And no duplicate record is created in the repository
    And the returned record has the same received_at timestamp as the original

  Scenario: Reject idempotency conflict — same triad, different content
    Given an entity mention with source_id "source_system_a", request_id "req_001", entity_type "person", and content '{"name": "Alice Dupont"}'
    And that entity mention has already been registered
    When the same triad is resubmitted with different content '{"name": "Acme Corp"}'
    Then an IdempotencyConflictError is raised
    And the original resolution request record remains unchanged in the repository
