Feature: Access control
  As a curation system
  I need to enforce role-based access to endpoints
  So that only authorised users can perform sensitive operations

  # --- Unauthenticated access ---

  Scenario: Unauthenticated access to curation endpoints is denied
    When an unauthenticated user requests the decision list
    Then the request is rejected with an authentication error

  # --- Unverified user ---

  Scenario: Unverified user cannot access curation endpoints
    Given a user is authenticated but not verified
    When the user requests the decision list
    Then the request is rejected with a forbidden error

  Scenario: Unverified user cannot curate decisions
    Given a user is authenticated but not verified
    When the user attempts to accept a decision
    Then the request is rejected with a forbidden error

  # --- Non-admin access to admin endpoints ---

  Scenario: Non-admin user cannot access user management
    Given a verified user is authenticated but is not an administrator
    When the user attempts to list all users
    Then the request is rejected with a forbidden error

  Scenario: Non-admin user cannot view user action trail
    Given a verified user is authenticated but is not an administrator
    When the user attempts to view the user action trail
    Then the request is rejected with a forbidden error

  Scenario: Non-admin user cannot create users
    Given a verified user is authenticated but is not an administrator
    When the user attempts to create a new user
    Then the request is rejected with a forbidden error

  # --- Admin access ---

  Scenario: Admin user can access user management endpoints
    Given an administrator is authenticated
    When the administrator requests the user list
    Then the user list is returned successfully

  Scenario: Admin user can view the user action trail
    Given an administrator is authenticated
    When the administrator requests the user action trail
    Then the action trail is returned successfully

  # --- Deactivated user ---

  Scenario: Deactivated user cannot access any endpoint
    Given a user is authenticated but has been deactivated
    When the user requests the decision list
    Then the request is rejected with an authentication error

  # --- Verified user access ---

  Scenario: Verified user can browse decisions
    Given a verified user is authenticated
    When the user requests the decision list
    Then the decision list is returned successfully

  Scenario: Verified user can view statistics
    Given a verified user is authenticated
    When the user requests curation statistics
    Then the statistics are returned successfully

  Scenario: Verified user can submit curation recommendations
    Given a verified user is authenticated
    When the user submits a curation recommendation for a decision
    Then the recommendation is accepted successfully