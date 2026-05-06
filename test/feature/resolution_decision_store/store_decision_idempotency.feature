Feature: Idempotent Decision Storage with Placement-Change Detection
  As the ERS Decision Store,
  I want to distinguish between a genuine placement change and an ERE re-confirmation of the same placement,
  So that updated_at is bumped only when the cluster assignment actually moves
  and downstream consumers see accurate delta signals.

  Background:
    Given the Decision Store is available

  # ---------------------------------------------------------------------------
  # First insert — created_at set, updated_at left unset
  # ---------------------------------------------------------------------------

  Scenario: First-time decision insert leaves updated_at unset
    Given no decision exists for entity mention triad "T-NEW"
    When a decision is stored for triad "T-NEW" with placement "cluster-A" and outcome timestamp "2026-05-05T10:00:00Z"
    Then a decision exists for triad "T-NEW" with placement "cluster-A"
    And the stored created_at is "2026-05-05T10:00:00Z"
    And the stored updated_at is unset

  # ---------------------------------------------------------------------------
  # ERE re-confirmation — no write, no timestamp bump
  # ---------------------------------------------------------------------------

  Scenario Outline: ERE re-confirmation of the same placement is a no-op
    Given a decision exists for triad "<triad>" with placement "<placement>" created_at "<created_at>" and updated_at unset
    When a decision is stored for triad "<triad>" with the same placement "<placement>" and a later outcome timestamp "<later_ts>"
    Then the stored decision is unchanged
    And the stored created_at is still "<created_at>"
    And the stored updated_at is still unset

    Examples:
      | triad        | placement | created_at              | later_ts                |
      | T-RECONFIRM1 | cluster-A | 2026-05-01T08:00:00Z    | 2026-05-05T10:00:00Z    |
      | T-RECONFIRM2 | cluster-B | 2026-04-01T00:00:00Z    | 2026-05-01T12:00:00Z    |

  # ---------------------------------------------------------------------------
  # Genuine placement change — updated_at set, created_at preserved
  # ---------------------------------------------------------------------------

  Scenario Outline: Genuine placement change sets updated_at and preserves created_at
    Given a decision exists for triad "<triad>" with placement "<old_placement>" created_at "<created_at>" and updated_at "<prior_updated_at>"
    When a decision is stored for triad "<triad>" with a different placement "<new_placement>" and outcome timestamp "<new_ts>"
    Then the stored decision has placement "<new_placement>"
    And the stored updated_at is "<new_ts>"
    And the stored created_at is still "<created_at>"

    Examples:
      | triad    | old_placement | new_placement | created_at           | prior_updated_at | new_ts               |
      | T-MOVE1  | cluster-A     | cluster-B     | 2026-05-01T08:00:00Z | unset            | 2026-05-05T10:00:00Z |
      | T-MOVE2  | cluster-B     | cluster-C     | 2026-04-01T00:00:00Z | 2026-04-15T06:00:00Z | 2026-05-01T12:00:00Z |

  # ---------------------------------------------------------------------------
  # Stale-outcome rejection
  # ---------------------------------------------------------------------------

  Scenario Outline: Stale write against an already-moved decision is rejected
    Given a decision exists for triad "<triad>" with placement "<placement>" and updated_at "<stored_ts>"
    When a decision is stored for triad "<triad>" with a different placement and outcome timestamp "<attempt_ts>"
    Then a StaleOutcomeError is raised
    And the stored decision is unchanged

    Examples:
      | triad       | placement | stored_ts               | attempt_ts              |
      | T-STALE1    | cluster-A | 2026-05-05T12:00:00Z    | 2026-05-05T11:59:59Z    |
      | T-STALE2    | cluster-A | 2026-05-05T12:00:00Z    | 2026-05-05T12:00:00Z    |

  Scenario Outline: Write against a never-moved decision compares to created_at
    Given a decision exists for triad "<triad>" with placement "cluster-A" created_at "<created_at>" and updated_at unset
    When a decision is stored for triad "<triad>" with a different placement "cluster-B" and outcome timestamp "<attempt_ts>"
    Then the outcome is "<outcome>"

    Examples:
      | triad      | created_at              | attempt_ts              | outcome    |
      | T-FRESH-1  | 2026-05-01T08:00:00Z    | 2026-05-05T10:00:00Z    | accepted   |
      | T-FRESH-2  | 2026-05-05T10:00:00Z    | 2026-05-01T08:00:00Z    | rejected   |
      | T-FRESH-3  | 2026-05-05T10:00:00Z    | 2026-05-05T10:00:00Z    | rejected   |
