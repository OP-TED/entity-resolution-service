Feature: Resolve Entity Mention via REST API (Spine A)
  As an originator submitting entity mentions for resolution,
  I want to POST single or bulk entity mentions and receive cluster identifiers,
  So that I can correlate my records to canonical entities within the client-facing time budget.

  Background:
    Given the ERS REST API is running
    And the Resolution Coordinator is available

  # ---------------------------------------------------------------------------
  # Main success — ERE responds within the execution window (canonical)
  # ---------------------------------------------------------------------------

  Scenario Outline: Canonical resolution when ERE responds within the execution window
    Given an entity mention with triad "<source_id>", "<request_id>", "<entity_type>"
    And the mention content is "<content_fixture>"
    And the mention context is "<context>"
    And the Resolution Coordinator returns canonical identifier "<canonical_id>"
    When I POST to /resolve
    Then the response HTTP status is <http_status>
    And the response body canonical_entity_id is "<canonical_id>"
    And the response body status is "<expected_status>"
    And the response body request_id is "<request_id>"

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        | canonical_id | http_status | expected_status |
      | SYSTEM_A  | req-001    | ORGANISATION | mock:org-001    | notice-2024-01 | cluster-010  | 200         | CANONICAL       |
      | SYSTEM_A  | req-002    | ORGANISATION | mock:org-002    | notice-2024-02 | cluster-011  | 200         | CANONICAL       |
      | SYSTEM_B  | req-003    | ORGANISATION | mock:org-003    |                | cluster-012  | 200         | CANONICAL       |

  # ---------------------------------------------------------------------------
  # Alternative success — ERE timeout or unreachable (provisional)
  # ---------------------------------------------------------------------------

  Scenario Outline: Provisional resolution when ERE does not respond in time or is unreachable
    Given an entity mention with triad "<source_id>", "<request_id>", "<entity_type>"
    And the mention content is "<content_fixture>"
    And the mention context is "<context>"
    And the Resolution Coordinator returns provisional identifier "<provisional_id>" due to "<reason>"
    When I POST to /resolve
    Then the response HTTP status is <http_status>
    And the response body canonical_entity_id is "<provisional_id>"
    And the response body status is "<expected_status>"
    And the response body request_id is "<request_id>"

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        | provisional_id     | reason          | http_status | expected_status |
      | SYSTEM_C  | req-010    | ORGANISATION | mock:org-004    | notice-2024-03 | prov-singleton-001 | ere_timeout     | 202         | PROVISIONAL     |
      | SYSTEM_C  | req-011    | ORGANISATION | mock:org-005    |                | prov-singleton-002 | ere_timeout     | 202         | PROVISIONAL     |
      | SYSTEM_D  | req-012    | ORGANISATION | mock:org-006    | notice-2024-04 | prov-singleton-003 | ere_unreachable | 202         | PROVISIONAL     |

  # ---------------------------------------------------------------------------
  # Idempotent replay — identical triad + content + context
  # ---------------------------------------------------------------------------

  Scenario Outline: Replay of an identical request returns the same identifier
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" was previously resolved
    And the original content was "<content_fixture>" with context "<context>"
    And the original resolution returned "<cluster_id>" with status "<original_status>" and HTTP <original_http>
    When I POST to /resolve with identical triad, content, and context
    Then the response HTTP status is <original_http>
    And the response body canonical_entity_id is "<cluster_id>"
    And the response body status is "<original_status>"

    Examples:
      | source_id | request_id | entity_type  | content_fixture | context        | cluster_id         | original_status | original_http |
      | SYSTEM_E  | req-020    | ORGANISATION | mock:org-001    | notice-2024-01 | cluster-010        | CANONICAL       | 200           |
      | SYSTEM_E  | req-021    | ORGANISATION | mock:org-004    | notice-2024-03 | prov-singleton-001 | PROVISIONAL     | 202           |
      | SYSTEM_E  | req-022    | ORGANISATION | mock:org-003    |                | cluster-012        | CANONICAL       | 200           |

  # ---------------------------------------------------------------------------
  # Idempotency conflict — same triad, different content or context
  # ---------------------------------------------------------------------------

  Scenario Outline: Reject request when triad reused with different content or context
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" was previously resolved
    And the original content was "<original_fixture>" with context "<original_context>"
    When I POST to /resolve with the same triad but content "<new_fixture>" and context "<new_context>"
    Then the response HTTP status is <http_status>
    And the response body error code is "<error_code>"
    And the response body contains a human-readable error message

    Examples:
      | source_id | request_id | entity_type  | original_fixture | original_context | new_fixture  | new_context    | http_status | error_code           |
      | SYSTEM_F  | req-030    | ORGANISATION | mock:org-001     | notice-2024-01   | mock:org-002 | notice-2024-01 | 400         | IDEMPOTENCY_CONFLICT |
      | SYSTEM_F  | req-031    | ORGANISATION | mock:org-002     | notice-2024-02   | mock:org-002 | notice-2024-99 | 400         | IDEMPOTENCY_CONFLICT |
      | SYSTEM_F  | req-032    | ORGANISATION | mock:org-003     | notice-2024-03   | mock:org-007 | notice-2024-99 | 400         | IDEMPOTENCY_CONFLICT |

  # ---------------------------------------------------------------------------
  # Validation errors — missing or malformed request fields
  # ---------------------------------------------------------------------------

  Scenario Outline: Reject resolve request with missing required fields
    Given an entity mention request with <missing_field> absent
    When I POST to /resolve
    Then the response HTTP status is <http_status>
    And the response body error code is "<error_code>"
    And the response body error detail references "<missing_field>"

    Examples:
      | missing_field | http_status | error_code       |
      | source_id     | 400         | VALIDATION_ERROR |
      | request_id    | 400         | VALIDATION_ERROR |
      | entity_type   | 400         | VALIDATION_ERROR |
      | content       | 400         | VALIDATION_ERROR |

  Scenario: Reject resolve request with unsupported entity type
    Given an entity mention with triad "SYSTEM_G", "req-040", "UNKNOWN_TYPE"
    And the mention content is "mock:org-001"
    When I POST to /resolve
    Then the response HTTP status is 400
    And the response body error code is "VALIDATION_ERROR"
    And the response body error detail references "entity_type"

  Scenario: Reject resolve request with malformed JSON body
    Given a POST /resolve request with a syntactically invalid JSON body
    When the request is submitted
    Then the response HTTP status is 400
    And the response body error code is "VALIDATION_ERROR"

  # ---------------------------------------------------------------------------
  # System failure — Resolution Coordinator unavailable
  # ---------------------------------------------------------------------------

  Scenario: Return service error when the Resolution Coordinator is unavailable
    Given an entity mention with triad "SYSTEM_H", "req-050", "ORGANISATION"
    And the mention content is "mock:org-001"
    And the Resolution Coordinator is unavailable
    When I POST to /resolve
    Then the response HTTP status is 500
    And the response body error code is "SERVICE_ERROR"

  # ===========================================================================
  # Bulk resolution — POST /resolveBulk
  #
  # Accepts a list of entity mentions, each processed independently within the
  # same client-facing time budget as a single resolve request.
  # Idempotency is enforced per mention (per triad), not per batch.
  #
  # Envelope HTTP status:
  #   200 — all mentions resolved canonically
  #   202 — all mentions received provisional identifiers
  #   207 — mixed outcomes (any combination of canonical, provisional, or error)
  #   400 — only when every mention in the batch fails validation
  #   500 — Resolution Coordinator unavailable (system-level failure)
  # ===========================================================================

  # ---------------------------------------------------------------------------
  # Bulk — uniform outcomes
  # ---------------------------------------------------------------------------

  Scenario Outline: Bulk resolve with uniform outcomes
    Given a batch of <count> entity mentions for entity_type "<entity_type>":
      | source_id   | request_id | content_fixture | context        |
      | <source_id> | <req_1>    | <fixture_1>     | <context_1>    |
      | <source_id> | <req_2>    | <fixture_2>     | <context_2>    |
      | <source_id> | <req_3>    | <fixture_3>     |                |
    And the Resolution Coordinator returns "<outcome>" for all mentions
    When I POST to /resolveBulk
    Then the response HTTP status is <http_status>
    And the response body contains <count> individual results
    And every individual result status is "<expected_status>"

    Examples:
      | count | entity_type  | source_id | req_1   | fixture_1    | context_1      | req_2   | fixture_2    | context_2      | req_3   | fixture_3    | outcome     | http_status | expected_status |
      | 3     | ORGANISATION | SYSTEM_A  | req-100 | mock:org-001 | notice-2024-10 | req-101 | mock:org-002 | notice-2024-11 | req-102 | mock:org-003 | canonical   | 200         | CANONICAL       |
      | 3     | ORGANISATION | SYSTEM_A  | req-200 | mock:org-004 | notice-2024-12 | req-201 | mock:org-005 | notice-2024-13 | req-202 | mock:org-006 | provisional | 202         | PROVISIONAL     |

  # ---------------------------------------------------------------------------
  # Bulk — mixed canonical and provisional outcomes
  # ---------------------------------------------------------------------------

  Scenario: Bulk resolve with mixed canonical and provisional outcomes
    Given a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context        |
      | SYSTEM_B  | req-300    | mock:org-001    | notice-2024-20 |
      | SYSTEM_B  | req-301    | mock:org-002    | notice-2024-21 |
      | SYSTEM_B  | req-302    | mock:org-003    |                |
    And the Resolution Coordinator returns per-mention outcomes:
      | request_id | outcome     | cluster_id         |
      | req-300    | canonical   | cluster-030        |
      | req-301    | provisional | prov-singleton-010 |
      | req-302    | canonical   | cluster-031        |
    When I POST to /resolveBulk
    Then the response HTTP status is 207
    And the response body contains 3 individual results
    And individual result for "req-300" has status "CANONICAL" and canonical_entity_id "cluster-030"
    And individual result for "req-301" has status "PROVISIONAL" and canonical_entity_id "prov-singleton-010"
    And individual result for "req-302" has status "CANONICAL" and canonical_entity_id "cluster-031"

  # ---------------------------------------------------------------------------
  # Bulk — partial validation failure (some succeed, some fail)
  # ---------------------------------------------------------------------------

  Scenario: Bulk resolve with partial validation failures returns mixed response
    Given a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context        |
      | SYSTEM_C  | req-400    | mock:org-001    | notice-2024-30 |
      | SYSTEM_C  | req-401    |                 | notice-2024-31 |
      | SYSTEM_C  | req-402    | mock:org-003    |                |
    And the Resolution Coordinator returns canonical identifier "cluster-040" for valid mentions
    When I POST to /resolveBulk
    Then the response HTTP status is 207
    And the response body contains 3 individual results
    And individual result for "req-400" has status "CANONICAL" and canonical_entity_id "cluster-040"
    And individual result for "req-401" has error code "VALIDATION_ERROR"
    And individual result for "req-402" has status "CANONICAL"

  # ---------------------------------------------------------------------------
  # Bulk — all mentions fail validation
  # ---------------------------------------------------------------------------

  Scenario: Bulk resolve rejected when all mentions fail validation
    Given a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context |
      | SYSTEM_D  |            | mock:org-001    |         |
      |           | req-501    | mock:org-002    |         |
      | SYSTEM_D  | req-502    |                 |         |
    When I POST to /resolveBulk
    Then the response HTTP status is 400
    And the response body error code is "VALIDATION_ERROR"
    And the response body contains 3 individual error details

  # ---------------------------------------------------------------------------
  # Bulk — per-mention idempotency within a batch
  # ---------------------------------------------------------------------------

  Scenario: Bulk resolve with an idempotent replay and a new mention
    Given a mention with triad "SYSTEM_E", "req-600", "ORGANISATION" was previously resolved
    And the original content was "mock:org-001" with context "notice-2024-40"
    And the original resolution returned "cluster-050" with status "CANONICAL" and HTTP 200
    And a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context        |
      | SYSTEM_E  | req-600    | mock:org-001    | notice-2024-40 |
      | SYSTEM_E  | req-601    | mock:org-002    | notice-2024-41 |
    And the Resolution Coordinator returns canonical identifier "cluster-051" for new mentions
    When I POST to /resolveBulk
    Then the response HTTP status is 200
    And individual result for "req-600" has status "CANONICAL" and canonical_entity_id "cluster-050"
    And individual result for "req-601" has status "CANONICAL" and canonical_entity_id "cluster-051"

  Scenario: Bulk resolve with an idempotency conflict within the batch
    Given a mention with triad "SYSTEM_F", "req-700", "ORGANISATION" was previously resolved
    And the original content was "mock:org-001" with context "notice-2024-50"
    And a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context        |
      | SYSTEM_F  | req-700    | mock:org-002    | notice-2024-50 |
      | SYSTEM_F  | req-701    | mock:org-003    | notice-2024-51 |
    And the Resolution Coordinator returns canonical identifier "cluster-060" for valid mentions
    When I POST to /resolveBulk
    Then the response HTTP status is 207
    And individual result for "req-700" has error code "IDEMPOTENCY_CONFLICT"
    And individual result for "req-701" has status "CANONICAL" and canonical_entity_id "cluster-060"

  # ---------------------------------------------------------------------------
  # Bulk — structural validation
  # ---------------------------------------------------------------------------

  Scenario: Reject bulk resolve with an empty mention list
    Given an empty batch of entity mentions
    When I POST to /resolveBulk
    Then the response HTTP status is 400
    And the response body error code is "VALIDATION_ERROR"
    And the response body error detail references "mentions"

  # ---------------------------------------------------------------------------
  # Bulk — system failure
  # ---------------------------------------------------------------------------

  Scenario: Return service error for bulk resolve when the Resolution Coordinator is unavailable
    Given a batch of entity mentions for entity_type "ORGANISATION":
      | source_id | request_id | content_fixture | context        |
      | SYSTEM_G  | req-800    | mock:org-001    | notice-2024-60 |
      | SYSTEM_G  | req-801    | mock:org-002    |                |
    And the Resolution Coordinator is unavailable
    When I POST to /resolveBulk
    Then the response HTTP status is 500
    And the response body error code is "SERVICE_ERROR"
