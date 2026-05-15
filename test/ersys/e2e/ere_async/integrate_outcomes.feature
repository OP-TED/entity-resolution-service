Feature: Integrate ERE Resolution Outcomes into the Decision Store
  As an operator of ERSys
  I want ERS to integrate clustering outcomes received from ERE into the Decision Store
  So that the canonical cluster assignment for each entity mention is always up to date and observable

  # Reference: UC-B1.2 — Integrate ERE Resolution Outcomes (docs/AnnexeB-UseCases/ucb12.adoc)
  # Reference: UC-W3  — Integrate ERE Reclustering (docs/AnnexeB-UseCases/ucw3.adoc)
  # Reference: docs/superpowers/specs/2026-04-02-e2e-test-architecture-design.md §5.4

  Background: System is clean and all services are healthy
    Given the ERS API is reachable
    And the decision store is empty
    And the ERE response channel is operational

  # ---------------------------------------------------------------------------
  # Scenario 1: Standard outcome — cluster assignment and alternatives stored
  # UC-B1.2 Main Success Scenario
  # ---------------------------------------------------------------------------

  Scenario: A standard ERE outcome stores the canonical cluster assignment and top alternatives in the decision store
    Given a previously submitted entity mention is registered in the request registry
    When a valid ERE clustering outcome is injected for that mention
    Then the decision store is updated with the canonical cluster identifier
    And the decision store contains the top alternative cluster candidates with their scores
    And the update timestamp in the decision store is refreshed

  # ---------------------------------------------------------------------------
  # Scenario 2: Draft identifier replaced by a canonical cluster assignment
  # UC-B1.2 Alternate Scenario — Draft Identifier Replacement
  # ---------------------------------------------------------------------------

  Scenario: A draft identifier in the decision store is replaced when ERE returns a canonical cluster assignment
    Given a previously submitted entity mention is registered with a provisional draft identifier in the decision store
    When a valid ERE clustering outcome is injected for that mention with a new canonical cluster identifier
    Then the decision store replaces the draft identifier with the canonical cluster identifier
    And the similarity scores from the ERE outcome are preserved without modification
    And the update timestamp in the decision store is refreshed

  # ---------------------------------------------------------------------------
  # Scenario 3: ERE confirms the provisional cluster as authoritative
  # UC-B1.2 Alternate Scenario — Draft Confirmed
  # ---------------------------------------------------------------------------

  Scenario: ERE confirms the provisional cluster assignment as authoritative
    Given a previously submitted entity mention is registered with a provisional draft identifier in the decision store
    When a valid ERE clustering outcome is injected confirming the same cluster identifier as authoritative
    Then the decision store retains the same cluster identifier
    And the update timestamp in the decision store is not set

  # ---------------------------------------------------------------------------
  # Scenario 4: ERE-initiated reclustering updates the decision store
  # UC-W3 — Integrate ERE Reclustering Results
  # ---------------------------------------------------------------------------

  Scenario: An ERE-initiated reclustering outcome updates the decision store and delta tracking
    Given entity mentions are registered and have existing cluster assignments in the decision store
    When ERE emits a reclustering outcome for one of those mentions with an updated cluster identifier
    Then the decision store reflects the new cluster assignment for the affected mention
    And the delta tracking is updated so that the change is visible through the next refresh operation
    And the cluster assignments of unaffected mentions are not changed

  # ---------------------------------------------------------------------------
  # Scenario 5: Duplicate outcome is handled idempotently
  # UC-B1.2 Minimal Guarantee — Duplicate / Out-of-Order
  # ---------------------------------------------------------------------------

  Scenario: Injecting the same ERE outcome a second time produces no further change in the decision store
    Given a previously submitted entity mention is registered in the request registry
    And a valid ERE clustering outcome has already been injected and processed for that mention
    When the same ERE clustering outcome is injected a second time
    Then the decision store is not changed by the second injection
    And no error condition is raised

  # ---------------------------------------------------------------------------
  # Scenario 6: Outcome for an unknown entity mention is discarded
  # UC-B1.2 Minimal Guarantee — Uncorrelated Outcome
  # ---------------------------------------------------------------------------

  Scenario: An ERE outcome for a mention that was never submitted is discarded without creating a decision record
    Given no entity mention with a particular triad has ever been submitted for resolution
    When an ERE clustering outcome is injected for that unknown triad
    Then no decision record is created in the decision store
    And no error condition is raised

  # ---------------------------------------------------------------------------
  # Scenario 7: Malformed ERE message is discarded and the system continues operating
  # UC-B1.2 Minimal Guarantee — Invalid Message
  # ---------------------------------------------------------------------------

  Scenario Outline: A structurally invalid ERE message is discarded without affecting the decision store
    Given entity mentions are registered and have existing cluster assignments in the decision store
    When a "<fault_type>" ERE message is injected into the response channel
    Then the decision store is not changed
    And the system continues to accept and process subsequent valid outcomes

    Examples:
      | fault_type                           |
      | missing cluster identifier           |
      | missing mention triad fields         |
      | empty message body                   |
      | non-JSON payload                     |
