Feature: Cluster Assignment Lookup via REST API (Spine C)
  As a downstream consumer observing canonical entity assignments,
  I want to look up current assignments for individual mentions
  and retrieve changed assignments in bulk since my last synchronisation,
  So that I can reconcile my local state with the latest authoritative placements
  without triggering any resolution or clustering activity.

  Background:
    Given the ERS REST API is running
    And the Decision Store is available

  # ---------------------------------------------------------------------------
  # Single-mention lookup — GET /api/v1/lookup
  # ---------------------------------------------------------------------------

  Scenario Outline: Look up current assignment for a known mention
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" exists in the Decision Store
    And the current cluster assignment is "<cluster_id>" last updated at "<last_updated>"
    When I GET /api/v1/lookup with source_id "<source_id>", request_id "<request_id>", entity_type "<entity_type>"
    Then the response HTTP status is <http_status>
    And the response body cluster_reference contains "<cluster_id>"
    And the response body last_updated is "<last_updated>"

    Examples:
      | source_id | request_id | entity_type  | cluster_id  | last_updated             | http_status |
      | SYSTEM_A  | req-001    | ORGANISATION | cluster-010 | 2026-03-15T10:00:00+00:00 | 200         |
      | SYSTEM_A  | req-002    | ORGANISATION | cluster-011 | 2026-03-15T11:30:00+00:00 | 200         |
      | SYSTEM_B  | req-003    | ORGANISATION | cluster-012 | 2026-03-16T09:00:00+00:00 | 200         |

  Scenario: Return not found when the mention triad is unknown
    Given no mention with triad "SYSTEM_UNKNOWN", "req-999", "ORGANISATION" exists in the Decision Store
    When I GET /api/v1/lookup with source_id "SYSTEM_UNKNOWN", request_id "req-999", entity_type "ORGANISATION"
    Then the response HTTP status is 404
    And the response body error code is "MENTION_NOT_FOUND"
    And the response body contains a human-readable error message

  Scenario Outline: Reject single lookup with missing or empty query parameters
    Given a GET /api/v1/lookup request with <param_condition>
    When the lookup request is submitted
    Then the response HTTP status is <http_status>
    And the response body error code is "<error_code>"
    And the response body error detail references "<invalid_param>"

    Examples:
      | param_condition            | invalid_param | http_status | error_code       |
      | source_id absent           | source_id     | 400         | VALIDATION_ERROR |
      | request_id absent          | request_id    | 400         | VALIDATION_ERROR |
      | entity_type absent         | entity_type   | 400         | VALIDATION_ERROR |
      | source_id set to empty     | source_id     | 400         | VALIDATION_ERROR |
      | request_id set to empty    | request_id    | 400         | VALIDATION_ERROR |
      | entity_type set to empty   | entity_type   | 400         | VALIDATION_ERROR |

  # ---------------------------------------------------------------------------
  # Bulk lookup (refresh-bulk) — POST /api/v1/refresh-bulk
  #
  # Downstream consumers call this endpoint to retrieve a bounded page of
  # assignment changes since their last synchronisation snapshot for a given
  # source. The service handles snapshot advancement internally.
  # ---------------------------------------------------------------------------

  Scenario Outline: Retrieve changed assignments since the last synchronisation snapshot
    Given source "<source_id>" has <expected_count> changed assignments to return with has_more <has_more>
    When I POST to /api/v1/refresh-bulk for source "<source_id>" with limit <limit>
    Then the response HTTP status is <http_status>
    And the response body contains <expected_count> delta assignments
    And each delta has identified_by, cluster_reference, and last_updated fields
    And the response body has_more is <has_more>

    Examples:
      | source_id | limit | expected_count | has_more | http_status |
      | SYSTEM_C  | 1000  | 3              | false    | 200         |
      | SYSTEM_C  | 1000  | 0              | false    | 200         |
      | SYSTEM_D  | 50    | 50             | true     | 200         |

  Scenario: First bulk lookup for a source returns all assignments
    Given source "SYSTEM_NEW" has 4 changed assignments to return with has_more false
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_NEW" with no continuation cursor
    Then the response HTTP status is 200
    And the response body contains 4 delta assignments

  Scenario: Page through a large delta set until exhausted
    Given source "SYSTEM_E" has 7 changed assignments spread across 3 pages with page size 3
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_E" with limit 3
    Then the response HTTP status is 200
    And the response body contains 3 delta assignments
    And the response body has_more is true
    And the continuation cursor is present
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_E" using the returned continuation cursor with limit 3
    Then the response HTTP status is 200
    And the response body contains 3 delta assignments
    And the response body has_more is true
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_E" using the returned continuation cursor with limit 3
    Then the response HTTP status is 200
    And the response body contains 1 delta assignment
    And the response body has_more is false
    And the continuation cursor is absent

  Scenario: Default page size is applied when limit is omitted
    Given source "SYSTEM_F" has 5 changed assignments to return with has_more false
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_F" without specifying a limit
    Then the response HTTP status is 200
    And the response body contains at most 1000 delta assignments

  Scenario Outline: Reject bulk lookup with invalid request fields
    Given a refresh-bulk request with <field_condition>
    When I POST to /api/v1/refresh-bulk
    Then the response HTTP status is <http_status>
    And the response body error code is "<error_code>"
    And the response body error detail references "<invalid_field>"

    Examples:
      | field_condition        | invalid_field | http_status | error_code       |
      | source_id absent       | source_id     | 400         | VALIDATION_ERROR |
      | source_id set to empty | source_id     | 400         | VALIDATION_ERROR |
      | limit set to zero      | limit         | 400         | VALIDATION_ERROR |
      | limit set to negative  | limit         | 400         | VALIDATION_ERROR |

  # ---------------------------------------------------------------------------
  # Service failures
  # ---------------------------------------------------------------------------

  Scenario: Return service error when Decision Store is unavailable for single lookup
    Given the lookup service raises a runtime error
    When I GET /api/v1/lookup with source_id "SYSTEM_G", request_id "req-060", entity_type "ORGANISATION"
    Then the response HTTP status is 500
    And the response body error code is "SERVICE_ERROR"

  Scenario: Return service error on bulk lookup
    Given the refresh-bulk service raises a runtime error
    When I POST to /api/v1/refresh-bulk for source "SYSTEM_H"
    Then the response HTTP status is 500
    And the response body error code is "SERVICE_ERROR"

  # ---------------------------------------------------------------------------
  # Read-only contract — neither endpoint modifies assignments or triggers resolution
  # ---------------------------------------------------------------------------

  Scenario: Lookup operations do not modify assignments or trigger resolution
    Given a mention with triad "SYSTEM_I", "req-070", "ORGANISATION" exists in the Decision Store
    And the current cluster assignment is "cluster-090" last updated at "2026-03-15T10:00:00+00:00"
    And source "SYSTEM_I" has 2 changed assignments to return with has_more false
    When I GET /api/v1/lookup with source_id "SYSTEM_I", request_id "req-070", entity_type "ORGANISATION"
    And I POST to /api/v1/refresh-bulk for source "SYSTEM_I" with limit 1000
    Then no resolution service method was invoked
