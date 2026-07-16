Feature: Retrieve Resolution Decision

  Scenario: Finding an existing decision by triad
    Given a stored decision for a known triad
    When I look up the decision by that triad
    Then the returned record matches the stored decision

  Scenario: Looking up a non-existent triad returns None
    Given an empty decision store
    When I look up a decision by an unknown triad
    Then the result is None
