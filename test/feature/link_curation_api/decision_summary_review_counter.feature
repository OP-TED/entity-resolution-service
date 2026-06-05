Feature: Decision summary previous-review counter
  As a curator
  I want to see how many times a decision has been curated in the past
  So that I can prioritise decisions that have already been reviewed

  Background:
    Given the curator is authenticated and verified

  Scenario: Fresh decision starts at 0
    Given a decision was just integrated from ERE with no prior curator actions
    When the curator requests the decisions list
    Then the row for that decision has previous_review_count equal to 0

  Scenario: Counter increments on accept action
    Given a decision with previous_review_count equal to 0
    When the curator records an accept action on that decision
    Then the row for that decision has previous_review_count equal to 1

  Scenario: Counter is preserved across ERE re-integration
    Given a decision with previous_review_count equal to 3
    When ERE re-integrates a new outcome for the same decision
    Then the row for that decision still has previous_review_count equal to 3
    And the current_placement reflects the new ERE outcome

  Scenario: A curator action flips reviewed_since_placement to true
    Given a decision with previous_review_count equal to 0
    When the curator records an accept action on that decision
    Then the row for that decision has reviewed_since_placement equal to true

  Scenario: ERE re-integration resets reviewed_since_placement to false
    Given a decision with previous_review_count equal to 3
    When ERE re-integrates a new outcome for the same decision
    Then the row for that decision has reviewed_since_placement equal to false
