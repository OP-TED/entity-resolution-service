Feature: Paginated Query of Decisions

  Scenario: First page with no cursor returns results and a next cursor
    Given 5 stored decisions
    When I query decisions with page_size 3 and no cursor
    Then I receive 3 records
    And the response includes a next_cursor

  Scenario: Following the cursor returns remaining decisions
    Given 5 stored decisions
    When I query page 1 then follow the next_cursor
    Then page 2 contains 2 records with no next_cursor

  Scenario: Empty store returns empty page
    Given an empty decision store
    When I query decisions paginated
    Then I receive 0 records and no next_cursor

  Scenario: page_size is capped at system limit
    Given a valid decision store
    When I query with page_size 9999
    Then the effective page_size does not exceed 50
