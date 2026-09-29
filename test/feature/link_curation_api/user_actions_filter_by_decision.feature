Feature: Filter user actions by decision_id
  As a curation UI consumer
  I want to fetch the timeline of curator actions for a single decision
  So that I can display the full curator history in the detail panel

  Background:
    Given the curator is authenticated and verified

  Scenario: Filter by decision_id returns the entity's full curator timeline
    Given a decision has 3 user_actions recorded
    When I GET /api/v1/curation/user-actions with decision_id filter
    Then the response contains exactly those 3 actions

  Scenario: Decision without user_actions returns an empty page
    Given a decision has no user_actions
    When I GET /api/v1/curation/user-actions with decision_id filter
    Then the response contains 0 results

  Scenario: decision_id filter composes with action_type filter
    Given a decision has actions of type ACCEPT_TOP and REJECT_ALL
    When I GET /api/v1/curation/user-actions with decision_id and action_type=ACCEPT_TOP
    Then only the ACCEPT_TOP action is returned

  Scenario: Timeline persists across ERE re-integrations
    Given a decision reviewed both before and after an ERE re-integration
    When I GET /api/v1/curation/user-actions with decision_id filter
    Then the response contains both the pre- and post-re-integration actions
