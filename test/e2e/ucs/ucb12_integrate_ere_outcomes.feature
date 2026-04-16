Feature: UC-B1.2 — Integrate ERE Resolution Outcomes (Asynchronous)
  As the Entity Resolution System integrating clustering outcomes from ERE,
  I want to update the Decision Store with the latest authoritative cluster assignment
  for each mention as outcomes arrive asynchronously,
  So that downstream consumers observe the latest canonical identity
  via lookup and refreshBulk operations.

  # Spine B integration test. The actor is ERS itself (internal).
  # ERE outcomes arrive via the messaging middleware.
  # The trigger is an ERE clustering outcome message, not an HTTP request.
  # Traceability: UC-B1.2, ADR-A1N, ADR-A2N.

  Background:
    Given the ERS system is operational
    And the Decision Store is available
    And the ERE messaging boundary is available

  # ---------------------------------------------------------------------------
  # Main Success — standard resolution outcome
  # ---------------------------------------------------------------------------

  Scenario Outline: Update Decision Store when ERE returns a clustering outcome
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" is registered
    And the Decision Store holds "<prior_cluster>" for that triad
    And ERE emits a clustering outcome for that mention with cluster "<new_cluster>" and <alt_count> alternatives
    When ERS consumes the outcome message
    Then the Decision Store reflects cluster "<new_cluster>" for triad "<source_id>", "<request_id>", "<entity_type>"
    And the Decision Store stores exactly <alt_count> alternative candidates
    And the alternative candidate scores are preserved exactly as ERE returned them
    And the delta tracking timestamp for that mention is updated

    Examples:
      | source_id | request_id | entity_type  | prior_cluster | new_cluster | alt_count |
      | SYSTEM_A  | req-001    | ORGANISATION | cluster-010   | cluster-010 | 3         |
      | SYSTEM_A  | req-002    | ORGANISATION | cluster-011   | cluster-020 | 5         |
      | SYSTEM_B  | req-003    | ORGANISATION |               | cluster-030 | 2         |

  # ---------------------------------------------------------------------------
  # Alternate — draft identifier replacement
  # ---------------------------------------------------------------------------

  Scenario: ERE replaces a provisional draft identifier with an authoritative cluster
    Given a mention with triad "SYSTEM_C", "req-010", "ORGANISATION" is registered
    And the Decision Store holds provisional draft identifier "prov-singleton-001" for that triad
    And ERE emits a clustering outcome with cluster "cluster-040" and 3 alternatives
    When ERS consumes the outcome message
    Then the Decision Store reflects cluster "cluster-040" for triad "SYSTEM_C", "req-010", "ORGANISATION"
    And the provisional draft identifier "prov-singleton-001" is no longer the current placement
    And the delta tracking timestamp for that mention is updated

  Scenario: ERE confirms a provisional draft identifier as the authoritative cluster
    Given a mention with triad "SYSTEM_C", "req-011", "ORGANISATION" is registered
    And the Decision Store holds provisional draft identifier "prov-singleton-002" for that triad
    And ERE emits a clustering outcome confirming cluster "prov-singleton-002" and 1 alternative
    When ERS consumes the outcome message
    Then the Decision Store reflects cluster "prov-singleton-002" for triad "SYSTEM_C", "req-011", "ORGANISATION"
    And the Decision Store stores exactly 1 alternative candidate
    And the delta tracking timestamp for that mention is updated

  # ---------------------------------------------------------------------------
  # Alternate — ERE-initiated reclustering
  # ---------------------------------------------------------------------------

  Scenario: ERE performs internal reclustering and emits an updated outcome
    Given a mention with triad "SYSTEM_D", "req-020", "ORGANISATION" is registered
    And the Decision Store holds "cluster-050" for that triad
    And ERE emits a reclustering outcome reassigning the mention to "cluster-060" with 4 alternatives
    When ERS consumes the outcome message
    Then the Decision Store reflects cluster "cluster-060" for triad "SYSTEM_D", "req-020", "ORGANISATION"
    And the Decision Store stores exactly 4 alternative candidates
    And the delta tracking timestamp for that mention is updated

  # ---------------------------------------------------------------------------
  # Idempotent / duplicate handling
  # ---------------------------------------------------------------------------

  Scenario: Duplicate ERE outcome for the same mention is processed idempotently
    Given a mention with triad "SYSTEM_E", "req-030", "ORGANISATION" is registered
    And the Decision Store holds "cluster-070" for that triad
    And ERE emits a clustering outcome with cluster "cluster-070" and 3 alternatives
    When ERS consumes the outcome message
    Then the Decision Store reflects cluster "cluster-070" for triad "SYSTEM_E", "req-030", "ORGANISATION"
    When ERS consumes the same outcome message again
    Then the Decision Store still reflects cluster "cluster-070" for triad "SYSTEM_E", "req-030", "ORGANISATION"
    And no duplicate decision record is created

  # ---------------------------------------------------------------------------
  # Uncorrelated / invalid responses
  # ---------------------------------------------------------------------------

  Scenario: Reject an ERE outcome for an unknown triad
    Given no mention with triad "SYSTEM_UNKNOWN", "req-999", "ORGANISATION" is registered
    And ERE emits a clustering outcome for triad "SYSTEM_UNKNOWN", "req-999", "ORGANISATION" with cluster "cluster-phantom"
    When ERS consumes the outcome message
    Then the outcome is rejected
    And no decision is written to the Decision Store
    And the rejection is logged

  Scenario Outline: Reject an invalid ERE outcome message
    Given a mention with triad "SYSTEM_F", "req-040", "ORGANISATION" is registered
    And the Decision Store holds "cluster-080" for that triad
    And ERE emits an outcome message with <invalid_condition>
    When ERS consumes the outcome message
    Then the outcome is rejected
    And the Decision Store still reflects "cluster-080" for triad "SYSTEM_F", "req-040", "ORGANISATION"
    And the rejection is logged

    Examples:
      | invalid_condition                   |
      | cluster_id absent                   |
      | correlation triad fields missing    |
      | malformed message structure         |

  # ---------------------------------------------------------------------------
  # Score preservation (Special Requirement)
  # ---------------------------------------------------------------------------

  Scenario: ERS does not alter similarity or confidence scores from ERE
    Given a mention with triad "SYSTEM_H", "req-060", "ORGANISATION" is registered
    And ERE emits a clustering outcome with cluster "cluster-100" and alternatives:
      | cluster_id  | confidence | similarity |
      | cluster-101 | 0.92       | 0.87       |
      | cluster-102 | 0.78       | 0.65       |
      | cluster-103 | 0.55       | 0.42       |
    When ERS consumes the outcome message
    Then the Decision Store stores 3 alternatives with scores exactly as received:
      | cluster_id  | confidence | similarity |
      | cluster-101 | 0.92       | 0.87       |
      | cluster-102 | 0.78       | 0.65       |
      | cluster-103 | 0.55       | 0.42       |
