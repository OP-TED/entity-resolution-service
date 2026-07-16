Feature: Consult Resolution Statistics
  UC-W4 — Consult Resolution Statistics (docs/AnnexeB-UseCases/ucw4.adoc)
  As an authorised Curator monitoring operational workload
  I want to consult aggregated statistics about current entity resolution activity
  So that I can prioritise review efforts without inspecting individual records

  Background: System is clean and the curation service is reachable
    Given the Curation API is reachable
    And the decision store is empty
    And the request registry is empty

  # ---------------------------------------------------------------------------
  # UC-W4 — Main Success Scenario: Aggregated statistics for a known entity type
  # Reference: docs/AnnexeB-UseCases/ucw4.adoc §Success Guarantees
  # ---------------------------------------------------------------------------

  Scenario Outline: Aggregated statistics for a known entity type match the seeded state
    Given the decision store contains <mention_count> entity mentions of type "<entity_type>" across <cluster_count> canonical clusters
    And the request registry contains <mention_count> resolution requests for that entity type
    When an authorised Curator requests statistics for entity type "<entity_type>"
    Then the statistics response is returned successfully
    And the reported total mention count matches <mention_count>
    And the reported total cluster count matches <cluster_count>
    And the reported total resolution request count matches <mention_count>
    And the decision store state is not modified by the statistics retrieval

    Examples:
      | entity_type   | mention_count | cluster_count |
      | ORGANISATION  | 10            | 4             |
      | PROCEDURE     | 7             | 3             |
      | ORGANISATION  | 1             | 1             |

  # ---------------------------------------------------------------------------
  # UC-W4 — Scenario: Zero counts when no data exists
  # Reference: docs/AnnexeB-UseCases/ucw4.adoc §Success Guarantees
  # ---------------------------------------------------------------------------

  Scenario: Statistics for an entity type return zero counts when no data has been recorded
    Given no entity mentions, clusters, or resolution requests exist in the system
    When an authorised Curator requests statistics for entity type "ORGANISATION"
    Then the statistics response is returned successfully
    And all reported counts are zero
    And the decision store remains empty

  # ---------------------------------------------------------------------------
  # UC-W4 — Invariant: Statistics retrieval is strictly read-only
  # Reference: docs/AnnexeB-UseCases/ucw4.adoc §Brief Description, §Postconditions
  # ---------------------------------------------------------------------------

  Scenario: Consulting statistics does not alter any system state
    Given the decision store contains a known set of entity mentions and cluster assignments
    And the request registry contains a known set of resolution requests
    When an authorised Curator requests statistics for entity type "ORGANISATION"
    Then the statistics response is returned successfully
    And the decision store contains exactly the same documents as before the call
    And the request registry contains exactly the same documents as before the call
    And no messages are published to the ERE request channel
