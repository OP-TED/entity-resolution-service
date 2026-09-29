Feature: Deduplicate ERE Outcomes Using Latest Assignment Wins
  As an ERS operator,
  I want the ERE Result Integrator to enforce the "latest assignment wins" rule
  using the monotonic outcome marker carried in each ERE outcome,
  So that stale, duplicate, and out-of-order deliveries never overwrite a more recent cluster assignment.

  Background:
    Given the Request Registry contains a mention with triad ("SYSTEM_A", "req-100", "Organization")
    And the Decision Store contains a cluster assignment for that triad with outcome marker "2026-03-12T14:30:45.123Z"

  Scenario Outline: Ignore an outcome whose timestamp does not advance the stored marker
    When the ERE delivers an outcome for that triad with outcome marker "<incoming_timestamp>" and cluster "<incoming_cluster>"
    Then the outcome is ignored without modifying the Decision Store
    And the Decision Store still holds the cluster assignment with outcome marker "2026-03-12T14:30:45.123Z"

    Examples:
      | incoming_timestamp         | incoming_cluster | reason                    |
      | 2026-03-12T14:30:44.000Z   | cluster-stale-1  | timestamp is earlier      |
      | 2026-03-12T14:30:45.123Z   | cluster-stale-2  | timestamp is equal        |
      | 2026-03-12T14:30:45.123Z   | cluster-stale-2  | duplicate redelivery      |

  Scenario: Only the latest outcome survives when arrivals are out of order
    Given the Decision Store is empty for a mention with triad ("SYSTEM_B", "req-200", "Organization")
    When the ERE delivers outcomes for that triad in this order:
      | outcome_marker               | cluster_id  |
      | 2026-03-12T16:00:00.000Z     | cluster-T3  |
      | 2026-03-12T14:00:00.000Z     | cluster-T1  |
      | 2026-03-12T15:00:00.000Z     | cluster-T2  |
    Then the Decision Store holds cluster assignment "cluster-T3" for that triad
