Feature: Bulk Cluster Assignment Lookup (refreshBulk — Spine C)
  As a downstream consumer synchronising cluster assignment changes,
  I want to retrieve all decisions that changed since my last lookup for a given source,
  So that I can reconcile my local state with the latest authoritative assignments
  without triggering any resolution or re-clustering activity.

  Background:
    Given the Resolution Coordinator is available with all dependency services
    And the Request Registry tracks lookup state per source

  Scenario Outline: Return decisions changed since the last lookup and advance the last notification date
    Given source "<source_id>" "<prior_lookup_state>"
    And the Decision Store contains <total_decisions> decisions for source "<source_id>" with <changed_count> updated since the last lookup
    When a bulk lookup is requested for source "<source_id>"
    Then <changed_count> cluster assignments are returned
    And <notification_date_action>

    Examples:
      | source_id | prior_lookup_state                                  | total_decisions | changed_count | notification_date_action                    |
      | SYSTEM_A  | last performed a bulk lookup at 2026-03-12T10:00:00 | 5               | 3             | the last notification date is advanced      |
      | SYSTEM_B  | last performed a bulk lookup at 2026-03-14T12:00:00 | 5               | 0             | the last notification date is advanced      |
      | SYSTEM_C  | has never performed a bulk lookup                   | 4               | 4             | a last notification date is created         |

  Scenario Outline: Reject a lookup that cannot be fulfilled
    Given source "<source_id>" "<precondition>"
    When a bulk lookup is requested for source "<source_id>"
    Then a "<error_type>" error is returned
    And the last notification date is not modified

    Examples:
      | source_id      | precondition                                            | error_type |
      | UNKNOWN        | has no resolution requests in the Request Registry      | not_found  |
      | SYSTEM_D       | last performed a bulk lookup but the Decision Store is unavailable | service    |

  Scenario: Bulk lookup is strictly read-only
    Given source "SYSTEM_A" last performed a bulk lookup at 2026-03-12T10:00:00
    When a bulk lookup is requested for source "SYSTEM_A"
    Then no resolution requests are published to the ERE
    And no decisions are written to the Decision Store
    And no requests are registered in the Request Registry
