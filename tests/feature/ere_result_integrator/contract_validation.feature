Feature: Validate ERE Outcome Messages Before Persisting
  As an ERS operator,
  I want the ERE Result Integrator to reject any outcome that does not satisfy
  the expected message contract or references an unknown correlation triad,
  So that the Decision Store is never corrupted by malformed or unresolvable outcomes.

  Background:
    Given the Decision Store contains a cluster assignment for triad ("SYSTEM_A", "req-300", "Organization") with outcome marker "2026-03-12T14:30:45.123Z"
    And the Request Registry contains a mention for that triad

  Scenario Outline: Reject a malformed outcome message
    When the ERE delivers an outcome message that is malformed because "<malformation>"
    Then an outcome validation error is raised
    And the Decision Store is not modified

    Examples:
      | malformation                             |
      | the entity_mention_id field is absent    |
      | the timestamp field is absent            |
      | all triad fields are null                |
      | the message body is an empty JSON object |
      | zero candidate alternatives are provided |

  Scenario Outline: Reject an outcome whose correlation triad is not in the Request Registry
    When the ERE delivers an outcome for a triad that is unknown because "<reason>"
    Then a triad-not-found error is raised
    And the Decision Store is not modified

    Examples:
      | reason                                         |
      | the source identifier is completely unknown    |
      | the request identifier does not exist          |
      | the entity type field is absent from the triad |

  Scenario Outline: Reject an outcome with an invalid outcome marker
    When the ERE delivers an outcome for a known triad with outcome marker "<invalid_timestamp>"
    Then an outcome validation error is raised
    And the Decision Store is not modified

    Examples:
      | invalid_timestamp   |
      | March 12 2026       |
      | 1741780245          |
      | 2026-03-12T14:30:45 |

  Scenario Outline: Reject an outcome with invalid candidate scores
    When the ERE delivers an outcome for a known triad with a candidate having confidence score "<confidence>" and similarity score "<similarity>"
    Then an outcome validation error is raised
    And the Decision Store is not modified

    Examples:
      | confidence | similarity | reason                   |
      | None       | 0.85       | confidence is missing    |
      | 0.90       | None       | similarity is missing    |
      | -0.50      | 0.85       | confidence below zero    |
      | 0.90       | 1.70       | similarity exceeds one   |
      | None       | None       | both scores are missing  |

  Scenario: Accept an outcome that carries unexpected extra fields
    When the ERE delivers a valid outcome for a known triad that also includes unrecognised fields
    Then no validation error is raised
    And the cluster assignment is persisted to the Decision Store
