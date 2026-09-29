Feature: Full Resolution Cycle — Cross-boundary E2E (UC-W1, UC-W2)
  As a downstream consumer of ERSys
  I want entity mentions submitted through the ERS API to be processed by the
  Entity Resolution Engine and their canonical cluster assignments to be
  retrievable through the same API
  So that I can rely on the end-to-end system to produce, update, and curate
  authoritative canonical identifiers across all component boundaries

  # Note: All scenarios in this feature require the full ERSys stack to be running:
  # ERS REST API, Curation API, ERE Worker, Redis, and FerretDB/MongoDB.
  # Run: make up && make test-e2e
  # Scenarios that wait for ERE use the polling helper (poll every 500ms, timeout 30s).

  Background: System is clean and all services are healthy
    Given the ERS API is reachable
    And the Curation API is reachable
    And the ERE worker is processing requests
    And the request registry is empty
    And the decision store is empty

  # ---------------------------------------------------------------------------
  # Scenario 1 — Happy path: direct engine response
  # UC-W1 Main Success Scenario: Direct Engine Response
  # Boundaries: ERS API -> Redis -> ERE -> Redis -> ERS API (lookup)
  # ---------------------------------------------------------------------------

  Scenario: Resolved mention receives a canonical cluster identifier after ERE processes it
    Given a valid entity mention for an organisation
    When the Originator submits the entity mention for resolution
    Then the submission is accepted
    When the system has finished processing the mention
    Then a lookup of the entity mention returns a canonical cluster identifier

  # ---------------------------------------------------------------------------
  # Scenario 2 — Provisional to canonical transition
  # UC-W1 Alternate Scenario: Draft Identifier Issuance
  # Boundaries: ERS API -> timeout -> ERE (delayed) -> ERS API (refresh-bulk)
  # ---------------------------------------------------------------------------

  Scenario: Mention issued a provisional identifier eventually transitions to a canonical assignment
    Given a valid entity mention for an organisation
    And the ERE execution window is shorter than the client timeout budget
    When the Originator submits the entity mention for resolution before ERE can respond
    Then the submission is accepted with a provisional draft identifier
    And the decision store contains a provisional cluster assignment for the mention
    When ERE later finishes processing the mention
    And the Originator requests a bulk notification refresh
    Then the refresh result includes the entity mention with a canonical cluster assignment
    And the cluster assignment recorded in the decision store is now canonical

  # ---------------------------------------------------------------------------
  # Scenario 3 — Idempotent replay: same mention submitted twice
  # UC-W1 Extension 2a: Idempotent Replay
  # Boundaries: ERS API x2 -> lookup
  # ---------------------------------------------------------------------------

  Scenario: Submitting the same entity mention twice returns consistent results and creates no duplicate registry entry
    Given a valid entity mention for an organisation
    When the Originator submits the entity mention for resolution
    And the system has finished processing the mention
    And the Originator submits the same entity mention for resolution a second time
    And the system has finished processing the mention
    Then both responses contain the same canonical cluster identifier
    And a lookup of the entity mention returns the same canonical cluster identifier
    And the decision store contains exactly one cluster assignment for that entity mention

  # ---------------------------------------------------------------------------
  # Scenario 4 — Batch resolution: multiple mentions all appear in refresh-bulk
  # UC-W1 Success Guarantee: multiple submissions
  # Boundaries: ERS API (multiple) -> ERE -> ERS API (refresh-bulk)
  # ---------------------------------------------------------------------------

  Scenario Outline: Multiple entity mentions submitted in sequence each receive a canonical cluster assignment visible in the bulk refresh
    Given a valid entity mention for <entity_type> using content "<mention_label>"
    When the Originator submits the entity mention for resolution
    Then the submission is accepted

    Examples:
      | entity_type  | mention_label        |
      | ORGANISATION | org-group1-file1     |
      | ORGANISATION | org-group1-file2     |
      | PROCEDURE    | proc-group1-file1    |

  Scenario: All batch-submitted entity mentions appear in the bulk notification refresh with canonical assignments
    Given the three entity mentions from the batch have each been submitted for resolution
    When the system has finished processing all three mentions
    And new cluster assignments have been injected for each of the three mentions
    And the Originator requests a bulk notification refresh
    Then the refresh result includes all three entity mentions
    And each entity mention in the refresh result has a canonical cluster assignment
    And each canonical cluster identifier in the refresh result originates from ERE

  # ---------------------------------------------------------------------------
  # Scenario 5 — Curation loop: resolve -> curate -> re-process -> new assignment
  # UC-W1 + UC-W2 combined
  # Boundaries: ERS API -> Curation API -> Redis -> ERE -> ERS API (lookup)
  # ---------------------------------------------------------------------------

  Scenario: A curator recommendation for a different cluster is acted upon by ERE and the new assignment is visible on lookup
    Given a valid entity mention for an organisation
    When the Originator submits the entity mention for resolution
    And the system has finished processing the mention
    Then a lookup of the entity mention returns an initial canonical cluster identifier
    And the cluster assignment is recorded in the decision store
    When an authorised curator submits a placement recommendation for a different cluster
    Then the placement recommendation is accepted without immediately modifying the cluster assignment
    And the user action is recorded in the user action log
    And a re-evaluation request is forwarded to ERE
    When ERE has finished re-processing the mention based on the placement recommendation
    Then a lookup of the entity mention returns an updated canonical cluster identifier
    And the updated cluster assignment is recorded in the decision store
    And the delta tracking is updated to reflect the change in cluster assignment
