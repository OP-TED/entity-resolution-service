Feature: Submit Bulk Curator Re-evaluation Requests
  UC-B2.2 — Submit Bulk Curator Re-evaluation (docs/AnnexeB-UseCases/ucb22.adoc)
  As an authorised Curator managing multiple entity mentions
  I want to submit a bulk re-evaluation request covering several mentions at once
  So that ERE can independently re-cluster each mention without me modifying any cluster assignment directly

  Background: System is clean, authenticated, and the curation service is reachable
    Given the Curation API is reachable
    And the user action log is empty
    And the decision store is empty
    And the ERE request channel is empty

  # ---------------------------------------------------------------------------
  # UC-B2.2 — Main Success Scenario: Bulk placement for N valid mentions
  # Reference: docs/AnnexeB-UseCases/ucb22.adoc §Main Success Scenario
  # ---------------------------------------------------------------------------

  Scenario Outline: Bulk placement recommendation for valid mentions creates independent action log entries and ERE messages
    Given <mention_count> entity mentions exist in the decision store each with a current cluster assignment
    When an authorised Curator submits a bulk placement recommendation for all <mention_count> mentions
    Then the bulk re-evaluation request is accepted
    And <mention_count> independent entries are created in the user action log
    And <mention_count> independent re-evaluation messages are published to the ERE request channel
    And none of the cluster assignments in the decision store are modified

    Examples:
      | mention_count |
      | 2             |
      | 5             |
      | 10            |

  # ---------------------------------------------------------------------------
  # UC-B2.2 — Extension 1a: Partial success — valid mentions proceed, invalid rejected
  # Reference: docs/AnnexeB-UseCases/ucb22.adoc §Extensions 1a
  # ---------------------------------------------------------------------------

  Scenario: Bulk submission where some mentions are invalid results in partial success
    Given 3 entity mentions exist in the decision store each with a current cluster assignment
    And 2 additional mention identifiers that do not exist in the decision store
    When an authorised Curator submits a bulk placement recommendation for all 5 mentions
    Then the bulk re-evaluation request returns a partial success outcome
    And 3 action log entries are created for the valid mentions
    And 3 re-evaluation messages are published to the ERE request channel for the valid mentions
    And the response includes individual rejection details for each invalid mention
    And none of the cluster assignments for the valid mentions in the decision store are modified

  # ---------------------------------------------------------------------------
  # UC-B2.2 — Minimal Guarantee: Empty selection rejected
  # Reference: docs/AnnexeB-UseCases/ucb22.adoc §Minimal Guarantees
  # ---------------------------------------------------------------------------

  Scenario: Bulk re-evaluation request with no mentions selected is rejected without side effects
    When an authorised Curator submits a bulk re-evaluation request with an empty selection of mentions
    Then the bulk re-evaluation request is rejected as invalid
    And no entries are created in the user action log
    And no messages are published to the ERE request channel
