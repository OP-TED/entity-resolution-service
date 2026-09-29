Feature: Refresh-Bulk Cold-Start and Idempotent ERE Re-confirmation Semantics
  As a downstream consumer synchronising cluster assignment changes,
  I want refresh-bulk to return only decisions whose placement has actually moved,
  So that I am not flooded with noise from stable resolutions or ERE re-confirmations
  and can trust that every delta in the response represents a genuine change.

  Background:
    Given the Resolution Coordinator is available with all dependency services
    And the Request Registry tracks lookup state per source
    And the Decision Store persists placement decisions per entity mention triad

  # ---------------------------------------------------------------------------
  # F-01: Cold start — source whose placements have never changed → empty delta
  # ---------------------------------------------------------------------------

  Scenario Outline: Cold-start refresh-bulk is empty when no placement has ever changed
    Given source "<source_id>" has never performed a bulk lookup
    And source "<source_id>" has <mention_count> registered entity mentions
    And ERE has only ever confirmed the same placement for each of those mentions
    And therefore all decisions for source "<source_id>" have an unset updated_at
    When a bulk lookup is requested for source "<source_id>"
    Then the response contains no cluster assignment deltas
    And has_more is false
    And the last notification date for source "<source_id>" is created and advanced to now

    Examples:
      | source_id  | mention_count |
      | SOURCE_F01 | 1             |
      | SOURCE_F01 | 5             |
      | SOURCE_F01 | 20            |

  # ---------------------------------------------------------------------------
  # F-02: Cold start — source with some corrected placements → only changed ones
  # ---------------------------------------------------------------------------

  Scenario Outline: Cold-start refresh-bulk returns only decisions whose placement was corrected
    Given source "<source_id>" has never performed a bulk lookup
    And source "<source_id>" has <total_mentions> registered entity mentions
    And <stable_count> of those have always kept the same placement and therefore have an unset updated_at
    And <changed_count> of those had their placement corrected at least once and therefore have a non-null updated_at
    When a bulk lookup is requested for source "<source_id>"
    Then the response contains exactly <changed_count> cluster assignment deltas
    And the <stable_count> mentions with an unset updated_at are not present in the response
    And has_more is false
    And the last notification date for source "<source_id>" is created and advanced to now

    Examples:
      | source_id  | total_mentions | stable_count | changed_count |
      | SOURCE_F02 | 5              | 4            | 1             |
      | SOURCE_F02 | 5              | 3            | 2             |
      | SOURCE_F02 | 5              | 0            | 5             |

  # ---------------------------------------------------------------------------
  # F-03: Ongoing consumer — ERE re-confirms same placement → NOT in next delta
  # ---------------------------------------------------------------------------

  Scenario: Ongoing consumer does not see a mention again after ERE re-confirms an unchanged placement
    Given source "SOURCE_F03" last performed a bulk lookup at "2026-05-01T09:00:00Z"
    And the Decision Store contains a decision for mention "mention-alpha" of source "SOURCE_F03" whose placement was last changed at "2026-04-30T08:00:00Z"
    And that decision was therefore included in a prior bulk lookup response
    When ERE re-confirms the same placement for mention "mention-alpha" with a later outcome timestamp
    And the Decision Store records the re-confirmation without changing updated_at
    And a subsequent bulk lookup is requested for source "SOURCE_F03"
    Then mention "mention-alpha" is not present in the response
    And has_more is false
    And the last notification date for source "SOURCE_F03" is advanced to now
