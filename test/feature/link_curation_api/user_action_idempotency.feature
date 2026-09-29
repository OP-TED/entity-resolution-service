Feature: User action idempotency guard (TEDSWS-522)
  As the entity resolution system
  I need to prevent double-curation on any decision version
  So that the user action trail is consistent and audit-safe

  Background:
    Given the curator is authenticated and verified

  # TEDSWS-522 regression: fresh decision (updated_at = None) was not guarded
  Scenario: Cannot re-accept a fresh decision (TEDSWS-522 regression)
    Given a fresh decision with no prior ERE integration and an accept already recorded
    When the curator attempts to accept the same decision again
    Then the system responds with a conflict error indicating already curated

  Scenario: Cannot double-act on the same fresh placement
    Given a fresh decision with no prior ERE integration and a reject already recorded
    When the curator attempts to reject the same decision again
    Then the system responds with a conflict error indicating already curated

  Scenario: New action allowed after ERE re-integration advances updated_at
    Given a decision whose updated_at has advanced after ERE re-integration
    And no action has been recorded since the latest re-integration
    When the curator accepts the re-integrated decision
    Then the recommendation is recorded
