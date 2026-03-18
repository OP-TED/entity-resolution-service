Feature: Accept and Persist ERE Resolution Outcomes
  As an ERS operator,
  I want the ERE Result Integrator to reliably absorb every valid ERE outcome
  and persist the latest cluster assignment to the Decision Store,
  So that all downstream consumers always see the authoritative clustering decision.

  Background:
    Given the Request Registry contains a mention for each correlation triad used in the scenarios below
    And the Decision Store contains no prior cluster assignment for those triads

  Scenario Outline: Accept a valid solicited resolution outcome
    Given the mention with triad ("<source_id>", "<request_id>", "Organization") exists in the Request Registry
    When the ERE publishes a solicited outcome for that triad with outcome timestamp "<outcome_timestamp>", primary cluster "<cluster_id>", and "<candidate_count>" alternative candidates
    Then the Decision Store is updated with cluster assignment "<cluster_id>" for that triad
    And the outcome marker stored in the Decision Store equals "<outcome_timestamp>"
    And all "<candidate_count>" alternative candidates are stored alongside the primary cluster assignment

    Examples:
      | source_id | request_id | outcome_timestamp          | cluster_id    | candidate_count |
      | SYSTEM_A  | req-001    | 2026-03-12T14:30:45.123Z   | cluster-org-1 | 2               |
      | SYSTEM_B  | req-002    | 2026-03-12T09:00:00.000Z   | cluster-org-7 | 1               |
      | SYSTEM_C  | req-003    | 2026-03-13T08:15:00.000Z   | cluster-org-4 | 0               |

  Scenario Outline: Accept an unsolicited reclustering outcome initiated by the ERE
    Given the mention with triad ("<source_id>", "<request_id>", "Organization") exists in the Request Registry
    And the Decision Store "<prior_state>" a prior cluster assignment for that triad
    When the ERE publishes an unsolicited outcome identified by "<ere_request_id>" with outcome timestamp "<outcome_timestamp>" and primary cluster "<cluster_id>"
    Then the Decision Store is updated with cluster assignment "<cluster_id>" for that triad
    And the outcome marker stored in the Decision Store equals "<outcome_timestamp>"

    Examples:
      | source_id | request_id | prior_state      | ere_request_id                | outcome_timestamp          | cluster_id     |
      | SYSTEM_A  | req-010    | contains         | ereNotification:rebuild       | 2026-03-14T10:00:00.000Z  | cluster-org-99 |
      | SYSTEM_B  | req-011    | does not contain | ereNotification:recluster-011 | 2026-03-14T10:05:00.000Z  | cluster-org-12 |

  Scenario Outline: Replace alternative candidates wholesale when a new outcome arrives
    Given the mention with triad ("<source_id>", "<request_id>", "Organization") exists in the Request Registry
    And the Decision Store contains an existing cluster assignment with "<prior_candidate_count>" alternative candidates
    When the ERE publishes a new outcome for that triad with outcome timestamp "<outcome_timestamp>" and "<new_candidate_count>" alternative candidates
    Then the Decision Store stores exactly "<new_candidate_count>" alternative candidates for that triad
    And no candidates from the prior outcome are retained

    Examples:
      | source_id | request_id | outcome_timestamp          | prior_candidate_count | new_candidate_count |
      | SYSTEM_A  | req-020    | 2026-03-15T12:00:00.000Z  | 3                     | 1                   |
      | SYSTEM_A  | req-021    | 2026-03-15T12:05:00.000Z  | 0                     | 3                   |
      | SYSTEM_A  | req-022    | 2026-03-15T12:10:00.000Z  | 2                     | 0                   |
