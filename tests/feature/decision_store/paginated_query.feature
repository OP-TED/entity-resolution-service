Feature: Paginated Query Over Resolution Decisions
  As a bulk synchronisation consumer,
  I want to retrieve resolution decisions in bounded, ordered pages
  using a continuation cursor,
  So that I can progressively synchronise all decisions without unbounded result sets.

  Background:
    Given the Decision Store is available

  Scenario: Walk through all pages until exhausted
    Given the Decision Store contains 7 resolution decisions with distinct outcome timestamps
    When the first page is queried with page size 3
    Then 3 decisions are returned ordered by outcome timestamp ascending
    And a continuation cursor is provided
    When the next page is queried using the continuation cursor
    Then 3 decisions are returned starting after the previous page
    And a continuation cursor is provided
    When the next page is queried using the continuation cursor
    Then 1 decision is returned
    And no continuation cursor is provided

  Scenario Outline: Query edge cases
    Given the Decision Store contains <decision_count> resolution decisions
    When decisions are queried with page size <page_size> and no cursor
    Then <returned_count> decisions are returned
    And <cursor_state>

    Examples:
      | decision_count | page_size | returned_count | cursor_state                       |
      | 0              | 3         | 0              | no continuation cursor is provided |
      | 2              | 5         | 2              | no continuation cursor is provided |
      | 5              | 3         | 3              | a continuation cursor is provided  |

  Scenario: Reject a malformed continuation cursor
    Given the Decision Store contains at least one resolution decision
    When decisions are queried with a malformed continuation cursor
    Then an invalid cursor error is raised
