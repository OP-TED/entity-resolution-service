Feature: User action listing
  As an administrator
  I need to browse recorded curation actions in reverse chronological order
  So that I can review curator activity and ensure quality

  Scenario: List user actions ordered by most recent first
    Given 5 user actions have been recorded at different times
    When the action listing is requested for page 1
    Then the actions are returned in reverse chronological order
    And the most recent action appears first

  Scenario: Paginate through user actions
    Given 25 user actions have been recorded
    When the action listing is requested for page 1 with 10 items per page
    Then 10 actions are returned
    And the total count is 25
    And a next page indicator points to page 2

  Scenario: Last page of user actions
    Given 25 user actions have been recorded
    When the action listing is requested for page 3 with 10 items per page
    Then 5 actions are returned
    And there is no next page indicator

  Scenario: Empty action listing
    Given no user actions have been recorded
    When the action listing is requested
    Then the result contains 0 actions
    And the total count is 0

  Scenario: User actions are enriched with entity mention previews
    Given a user action exists for an entity mention with a parsed representation
    When the action listing is requested
    Then each action summary includes the entity mention preview
    And the preview contains the parsed representation when available

  Scenario: User actions for missing entity mentions show partial previews
    Given a user action exists for an entity mention that has no parsed representation
    When the action listing is requested
    Then the action summary includes the entity mention identifier
    And the parsed representation is empty

  Scenario Outline: Filter the action trail by a single criterion
    Given user actions have been recorded by multiple curators across different recommendation types and time periods
    When the action listing is filtered by <filter criterion> matching <filter value>
    Then only actions matching <filter value> are returned
    And actions that do not match are excluded

    Examples:
      | filter criterion | filter value               |
      | recommendation type  | accept top recommendation  |
      | actor            | curator@example.com        |
      | time range       | last 7 days                |