Feature: Bulk curation operations
  As a curator
  I need to accept or reject multiple decisions in a single operation
  So that I can efficiently curate batches of similar decisions

  Background:
    Given the curator is authenticated and verified

  # --- Bulk accept ---

  Scenario: Bulk accept multiple decisions successfully
    Given 3 decisions exist that have not been curated
    When the curator bulk-accepts all 3 decisions
    Then the response contains 3 results all with status "success"

  Scenario: Bulk accept with partial failures
    Given 2 decisions exist that have not been curated
    And 1 decision does not exist
    When the curator bulk-accepts all 3 decision identifiers
    Then the response contains 2 results with status "success"
    And 1 result with status "not found"

  Scenario: Bulk accept with already curated decisions
    Given 1 decision has not been curated
    And 1 decision has already been curated on its current version
    When the curator bulk-accepts both decisions
    Then the response contains 1 result with status "success"
    And 1 result with status "already curated"

  # --- Bulk reject ---

  Scenario: Bulk reject multiple decisions successfully
    Given 3 decisions exist that have not been curated
    When the curator bulk-rejects all 3 decisions
    Then the response contains 3 results all with status "success"

  Scenario: Bulk reject with mixed outcomes
    Given 1 decision has not been curated
    And 1 decision has already been curated
    And 1 decision does not exist
    When the curator bulk-rejects all 3 decision identifiers
    Then the response contains 1 result with status "success"
    And 1 result with status "already curated"
    And 1 result with status "not found"

  # --- Validation ---

  Scenario: Bulk operation with empty decision list is rejected
    When the curator submits a bulk accept with no decision identifiers
    Then the request is rejected as invalid

  Scenario: Bulk operation respects maximum batch size
    When the curator submits a bulk accept with more than 200 decision identifiers
    Then the request is rejected as invalid