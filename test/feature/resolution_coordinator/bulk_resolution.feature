Feature: Resolve a Bulk Resolution Request
  As a service layer consumer of the Resolution Coordinator,
  I want a bulk resolve message unpacked into independent single-mention resolutions,
  each forwarded to the ERE and awaited within the time budget,
  So that the caller receives all results (canonical, provisional, or error) in one response.

  Background:
    Given the Resolution Coordinator is available with all dependency services
    And the ERE execution window is configured

  Scenario Outline: Unpack and resolve each mention independently
    Given a bulk resolve request containing <mention_count> entity mentions
    And <timeout_count> of those do not receive an ERE response in time
    And <error_count> of those have malformed RDF content
    When the bulk resolution request is submitted
    Then <mention_count> results are returned in the same order as the input
    And <error_count> of those results are errors

    Examples:
      | mention_count | timeout_count | error_count |
      | 3             | 0             | 0           |
      | 3             | 2             | 0           |
      | 3             | 0             | 1           |
      | 0             | 0             | 0           |

  Scenario Outline: Each mention resolves independently regardless of others
    Given a bulk resolve request containing 3 entity mentions
    And the <position> mention "<condition>"
    When the bulk resolution request is submitted
    Then the <position> mention returns "<result_type>"

    Examples:
      | position | condition                                              | result_type                      |
      | 1    | receives an ERE response within the execution window   | canonical cluster identifier     |
      | 2    | has malformed RDF content                              | parsing failure error            |
      | 3    | does not receive an ERE response in time               | provisional singleton identifier |
