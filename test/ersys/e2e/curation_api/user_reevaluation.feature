Feature: Submit User Re-evaluation Request
  UC-B2.1 — Submit User Re-evaluation Request (docs/AnnexeB-UseCases/ucb21.adoc)
  As an authorised Curator reviewing an entity mention
  I want to submit a re-evaluation request with a placement or exclusion recommendation
  So that ERE can re-cluster the mention without me directly overriding the canonical cluster assignment

  Background: System is clean, authenticated, and the curation service is reachable
    Given the Curation API is reachable
    And the user action log is empty
    And the decision store is empty
    And the ERE request channel is empty

  # ---------------------------------------------------------------------------
  # UC-B2.1 — Main Success Scenario: Placement Recommendation
  # Reference: docs/AnnexeB-UseCases/ucb21.adoc §Main Success Scenario
  # ---------------------------------------------------------------------------

  Scenario: Placement recommendation for a known mention is accepted and forwarded to ERE
    Given an entity mention exists in the decision store with a current cluster assignment
    When an authorised Curator submits a placement recommendation for that mention recommending a target cluster
    Then the re-evaluation request is accepted
    And an entry is created in the user action log recording the Curator's recommendation
    And a re-evaluation message is published to the ERE request channel
    And the current cluster assignment in the decision store is not modified

  # ---------------------------------------------------------------------------
  # UC-B2.1 — Alternate Scenario: Exclusion Recommendation
  # Reference: docs/AnnexeB-UseCases/ucb21.adoc §Alternate Scenario
  # ---------------------------------------------------------------------------

  Scenario: Exclusion recommendation for a known mention is accepted and forwarded to ERE with an exclusion list
    Given an entity mention exists in the decision store with a current cluster assignment
    When an authorised Curator submits an exclusion recommendation for that mention specifying clusters to exclude
    Then the re-evaluation request is accepted
    And an entry is created in the user action log recording the exclusion recommendation
    And a re-evaluation message is published to the ERE request channel carrying the list of excluded clusters
    And the current cluster assignment in the decision store is not modified

  # ---------------------------------------------------------------------------
  # UC-B2.1 — Minimal Guarantee: Unknown mention rejected
  # Reference: docs/AnnexeB-UseCases/ucb21.adoc §Minimal Guarantees
  # ---------------------------------------------------------------------------

  Scenario: Re-evaluation request for an unknown entity mention is rejected without side effects
    Given no entity mention with the requested source identifier, request identifier, and entity type exists in the decision store
    When an authorised Curator submits a placement recommendation for that unknown mention
    Then the re-evaluation request is rejected as not found
    And no entry is created in the user action log
    And no message is published to the ERE request channel

  # ---------------------------------------------------------------------------
  # UC-B2.1 — Minimal Guarantee: Validation failure on malformed request
  # ---------------------------------------------------------------------------

  Scenario Outline: Re-evaluation request with a missing required field is rejected without side effects
    Given an entity mention exists in the decision store with a current cluster assignment
    When an authorised Curator submits a re-evaluation request with the "<missing_field>" field omitted
    Then the re-evaluation request is rejected as invalid
    And no entry is created in the user action log
    And no message is published to the ERE request channel
    And the current cluster assignment in the decision store is not modified

    Examples:
      | missing_field         |
      | source_id             |
      | request_id            |
      | entity_type           |
      | recommendation_type   |

  # ---------------------------------------------------------------------------
  # UC-B2.1 — Minimal Guarantee: ERE unavailable — no partial state created
  # Reference: docs/AnnexeB-UseCases/ucb21.adoc §Minimal Guarantees
  # ---------------------------------------------------------------------------

  Scenario: Re-evaluation request cannot be forwarded when ERE is unavailable — current cluster assignment is preserved
    Given an entity mention exists in the decision store with a current cluster assignment
    And ERE is not available to receive re-evaluation requests
    When an authorised Curator submits a placement recommendation for that mention
    Then an error is returned indicating the re-evaluation could not be forwarded
    And the current cluster assignment in the decision store is not modified
    And no partial re-evaluation state is left in the system
