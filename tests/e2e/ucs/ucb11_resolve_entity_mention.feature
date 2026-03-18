Feature: UC-B1.1 — Resolve Entity Mention via ERS API
  As an originator submitting entity mentions for resolution,
  I want to receive a canonical cluster identifier for each valid mention
  within the client-facing timeout budget,
  So that I can correlate my records to authoritative canonical entities
  and continue processing without waiting for asynchronous engine outcomes.

  # Spine A integration test. ERE is mocked at the messaging boundary.
  # All other components (Request Registry, Coordinator, Decision Store) are real.
  # Traceability: UC-W1, UC-B1.1, ADR-A1N, ADR-A2N, ADR-C1N.

  Background:
    Given the ERS system is operational
    And the Request Registry is available
    And the Decision Store is available
    And the ERE messaging boundary is available

  # ---------------------------------------------------------------------------
  # Main Success Scenario — direct engine response (canonical)
  # ---------------------------------------------------------------------------

  Scenario Outline: Canonical resolution when ERE responds within the execution window
    Given an entity mention with triad "<source_id>", "<request_id>", "<entity_type>"
    And the mention content is "<content_fixture>" with context "<context>"
    And ERE will respond with cluster "<canonical_id>" and <alt_count> alternatives within the execution window
    When the originator submits the resolve request
    Then the response returns "<canonical_id>" with status "CANONICAL"
    And the request is registered in the Request Registry with triad "<source_id>", "<request_id>", "<entity_type>"
    And the Decision Store contains a decision for triad "<source_id>", "<request_id>", "<entity_type>" with cluster "<canonical_id>"
    And the Decision Store decision has <alt_count> alternative candidates
    And the Decision Store decision delta tracking timestamp is updated

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        | canonical_id | alt_count |
      | SYSTEM_A  | req-001    | ORGANISATION | mock:org-001    | notice-2024-01 | cluster-010  | 3         |
      | SYSTEM_A  | req-002    | ORGANISATION | mock:org-002    | notice-2024-02 | cluster-011  | 0         |
      | SYSTEM_B  | req-003    | ORGANISATION | mock:org-003    |                | cluster-012  | 5         |

  # ---------------------------------------------------------------------------
  # Alternate Scenario — ERE timeout, draft identifier issuance (provisional)
  # ---------------------------------------------------------------------------

  Scenario Outline: Provisional draft identifier when ERE does not respond within the execution window
    Given an entity mention with triad "<source_id>", "<request_id>", "<entity_type>"
    And the mention content is "<content_fixture>" with context "<context>"
    And ERE will not respond within the execution window
    When the originator submits the resolve request
    Then the response returns a deterministic draft identifier with status "PROVISIONAL"
    And the draft identifier equals SHA256 of "<source_id>", "<request_id>", "<entity_type>"
    And the request is registered in the Request Registry with triad "<source_id>", "<request_id>", "<entity_type>"
    And the Decision Store contains a provisional singleton decision for that triad
    And the Decision Store decision has confidence 1.0 and similarity 1.0
    And a resolveConsideringRecommendation message is forwarded to ERE with the draft identifier

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        |
      | SYSTEM_C  | req-010    | ORGANISATION | mock:org-004    | notice-2024-03 |
      | SYSTEM_C  | req-011    | ORGANISATION | mock:org-005    |                |

  # ---------------------------------------------------------------------------
  # Draft identifier determinism (ADR-A1N)
  # ---------------------------------------------------------------------------

  Scenario: Same triad always produces the same draft identifier
    Given an entity mention with triad "SYSTEM_D", "req-020", "ORGANISATION"
    And the mention content is "mock:org-006" with context "notice-2024-04"
    And ERE will not respond within the execution window
    When the originator submits the resolve request
    Then the response returns a deterministic draft identifier with status "PROVISIONAL"
    And the draft identifier equals SHA256 of "SYSTEM_D", "req-020", "ORGANISATION"
    When a second mention with the same triad "SYSTEM_D", "req-020", "ORGANISATION" is submitted with identical content and context
    And ERE will not respond within the execution window
    Then the response returns the same draft identifier as the first submission

  # ---------------------------------------------------------------------------
  # Idempotent replay — identical triad + content + context
  # ---------------------------------------------------------------------------

  Scenario Outline: Replay of an identical request returns the same identifier without duplicate registration
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" was previously resolved
    And the original content was "<content_fixture>" with context "<context>"
    And the original resolution returned "<cluster_id>" with status "<original_status>"
    When the originator submits the same resolve request with identical triad, content, and context
    Then the response returns "<cluster_id>" with status "<original_status>"
    And the Request Registry contains exactly one record for triad "<source_id>", "<request_id>", "<entity_type>"

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        | cluster_id         | original_status |
      | SYSTEM_E  | req-030    | ORGANISATION | mock:org-001    | notice-2024-01 | cluster-010        | CANONICAL       |
      | SYSTEM_E  | req-031    | ORGANISATION | mock:org-004    | notice-2024-03 | prov-singleton-001 | PROVISIONAL     |

  # ---------------------------------------------------------------------------
  # Idempotency conflict — same triad, different content or context
  # ---------------------------------------------------------------------------

  Scenario Outline: Reject request when triad reused with different payload
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" was previously resolved
    And the original content was "<original_fixture>" with context "<original_context>"
    When the originator submits a resolve request with the same triad but content "<new_fixture>" and context "<new_context>"
    Then the response returns error "IDEMPOTENCY_CONFLICT"
    And the Decision Store is not modified for triad "<source_id>", "<request_id>", "<entity_type>"

    Examples:
      | source_id | request_id | entity_type  | original_fixture | original_context | new_fixture  | new_context    |
      | SYSTEM_F  | req-040    | ORGANISATION | mock:org-001     | notice-2024-01   | mock:org-002 | notice-2024-01 |
      | SYSTEM_F  | req-041    | ORGANISATION | mock:org-002     | notice-2024-02   | mock:org-002 | notice-2024-99 |

  # ---------------------------------------------------------------------------
  # Validation errors (Extensions 1a, 1b)
  # ---------------------------------------------------------------------------

  Scenario Outline: Reject invalid resolve request before registration
    Given an invalid resolve request with <violation>
    When the originator submits the resolve request
    Then the response returns error "<error_code>"
    And no request is registered in the Request Registry
    And no decision is written to the Decision Store

    Examples:
      | violation                          | error_code       |
      | source_id absent                   | VALIDATION_ERROR |
      | request_id absent                  | VALIDATION_ERROR |
      | entity_type absent                 | VALIDATION_ERROR |
      | content absent                     | VALIDATION_ERROR |
      | entity_type set to "UNKNOWN_TYPE"  | VALIDATION_ERROR |

  # ---------------------------------------------------------------------------
  # Client timeout budget exceeded (ADR-A2N, ADR-C1N)
  # ---------------------------------------------------------------------------

  Scenario: Return explicit error when client timeout budget is exceeded
    Given an entity mention with triad "SYSTEM_G", "req-050", "ORGANISATION"
    And the mention content is "mock:org-001" with context "notice-2024-05"
    And ERE will not respond within the execution window
    And the client timeout budget is exceeded before a draft identifier can be issued
    When the originator submits the resolve request
    Then the response returns a timeout error
    And the request is registered in the Request Registry
    And no decision is written to the Decision Store

  # ---------------------------------------------------------------------------
  # Critical dependency failures
  # ---------------------------------------------------------------------------

  Scenario: Return service error when the Request Registry is unavailable
    Given an entity mention with triad "SYSTEM_H", "req-060", "ORGANISATION"
    And the mention content is "mock:org-001" with context "notice-2024-06"
    And the Request Registry is unavailable
    When the originator submits the resolve request
    Then the response returns error "SERVICE_ERROR"
    And no decision is written to the Decision Store

  Scenario: Return service error when the Decision Store fails after ERE response
    Given an entity mention with triad "SYSTEM_I", "req-070", "ORGANISATION"
    And the mention content is "mock:org-001" with context "notice-2024-07"
    And ERE will respond with cluster "cluster-020" and 2 alternatives within the execution window
    And the Decision Store will fail on write
    When the originator submits the resolve request
    Then the response returns error "SERVICE_ERROR"
    And the request is registered in the Request Registry with triad "SYSTEM_I", "req-070", "ORGANISATION"
