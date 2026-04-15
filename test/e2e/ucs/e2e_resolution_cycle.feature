Feature: End-to-End Resolution Cycle
  As an originator integrating with the Entity Resolution System,
  I want to submit mentions, receive identifiers, and later observe
  authoritative placement changes through bulk synchronisation,
  So that my downstream systems converge on the latest canonical identity
  as determined by the Entity Resolution Engine.

  # Lightweight, high-level, black-box E2E scenarios.
  # Tests the three-phase cycle visible at the ERS boundary:
  #   Phase 1 — Bounded intake (POST /api/v1/resolve → identifier)
  #   Phase 2 — Authoritative assessment (ERE outcome → Decision Store)
  #   Phase 3 — Convergence (GET /api/v1/lookup, POST /api/v1/refresh-bulk → observe changes)
  #
  # ERE is mocked at the messaging boundary. All ERS components are real.
  # Traceability: Section 8.1, UC-B1.1, UC-B1.2, UC-B1.3.

  Background:
    Given the ERS system is operational with all components
    And the ERE messaging boundary is available

  # ---------------------------------------------------------------------------
  # Main Success — canonical resolution observed via lookup and refresh-bulk
  # ---------------------------------------------------------------------------

  Scenario: Submit a mention, receive canonical identifier, verify via lookup and refresh-bulk
    Given an entity mention with triad "SYSTEM_A", "req-001", "ORGANISATION"
    And the mention content is "mock:org-001" with context "notice-2024-01"
    And ERE will respond with cluster "cluster-010" and 3 alternatives within the execution window
    When the originator submits the resolve request
    Then the response returns "cluster-010" with status "CANONICAL"
    When the originator looks up triad "SYSTEM_A", "req-001", "ORGANISATION"
    Then the lookup returns cluster "cluster-010"
    When the originator calls refresh-bulk for source "SYSTEM_A"
    Then the delta includes triad "SYSTEM_A", "req-001", "ORGANISATION" with cluster "cluster-010"

  # ---------------------------------------------------------------------------
  # Alternate — provisional identifier replaced by late ERE outcome
  # ---------------------------------------------------------------------------

  Scenario: Submit a mention, receive provisional identifier, ERE responds late, refresh-bulk shows updated cluster
    Given an entity mention with triad "SYSTEM_B", "req-010", "ORGANISATION"
    And the mention content is "mock:org-002" with context "notice-2024-02"
    And ERE will not respond within the execution window
    When the originator submits the resolve request
    Then the response returns a provisional draft identifier with status "PROVISIONAL"
    When the originator looks up triad "SYSTEM_B", "req-010", "ORGANISATION"
    Then the lookup returns the provisional draft identifier
    When ERE delivers a late outcome assigning triad "SYSTEM_B", "req-010", "ORGANISATION" to cluster "cluster-020"
    And the originator looks up triad "SYSTEM_B", "req-010", "ORGANISATION"
    Then the lookup returns cluster "cluster-020"
    When the originator calls refresh-bulk for source "SYSTEM_B"
    Then the delta includes triad "SYSTEM_B", "req-010", "ORGANISATION" with cluster "cluster-020"

  # ---------------------------------------------------------------------------
  # Idempotent replay — same request, same result, no drift
  # ---------------------------------------------------------------------------

  Scenario: Replay the same resolve request and verify consistent lookup
    Given an entity mention with triad "SYSTEM_D", "req-030", "ORGANISATION"
    And the mention content is "mock:org-004" with context "notice-2024-04"
    And ERE will respond with cluster "cluster-050" and 1 alternative within the execution window
    When the originator submits the resolve request
    Then the response returns "cluster-050" with status "CANONICAL"
    When the originator submits the same resolve request again
    Then the response returns "cluster-050" with status "CANONICAL"
    When the originator looks up triad "SYSTEM_D", "req-030", "ORGANISATION"
    Then the lookup returns cluster "cluster-050"

  # ---------------------------------------------------------------------------
  # Multiple mentions — refresh-bulk returns all changes, then empty
  # ---------------------------------------------------------------------------

  Scenario: Submit multiple mentions for the same source and observe all via refresh-bulk
    Given the following entity mentions are submitted and resolved:
      | source_id | request_id | entity_type  | content_fixture | cluster_id  |
      | SYSTEM_E  | req-040    | ORGANISATION | mock:org-005    | cluster-060 |
      | SYSTEM_E  | req-041    | ORGANISATION | mock:org-006    | cluster-061 |
      | SYSTEM_E  | req-042    | ORGANISATION | mock:org-007    | cluster-062 |
    When the originator calls refresh-bulk for source "SYSTEM_E"
    Then the delta contains 3 assignments
    And the delta includes triad "SYSTEM_E", "req-040", "ORGANISATION" with cluster "cluster-060"
    And the delta includes triad "SYSTEM_E", "req-041", "ORGANISATION" with cluster "cluster-061"
    And the delta includes triad "SYSTEM_E", "req-042", "ORGANISATION" with cluster "cluster-062"
    When the originator calls refresh-bulk for source "SYSTEM_E" again
    Then the delta contains 0 assignments
