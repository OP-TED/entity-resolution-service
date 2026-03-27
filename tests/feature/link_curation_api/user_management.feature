Feature: User management
  As an administrator
  I need to create, list, update, and deactivate user accounts
  So that I can control who has access to curation functionality while preserving traceability

  Background:
    Given the administrator is authenticated

  # --- Create user ---

  Scenario: Create a new user
    When the administrator creates a user with email "newcurator@example.com"
    Then the user account is created
    And the response contains the user details without the password

  Scenario: Create a user with a duplicate email
    Given a user exists with email "existing@example.com"
    When the administrator creates a user with email "existing@example.com"
    Then the creation is rejected because the email is already in use

  # --- List users ---

  Scenario: List all users with pagination
    Given 15 user accounts exist
    When the administrator requests the user list with 10 items per page
    Then 10 users are returned
    And the total count is 15

  # --- Update user ---

  Scenario Outline: Update user flags
    Given a user account exists
    When the administrator sets the user's "<flag>" to <value>
    Then the user record reflects the updated flag

    Examples:
      | flag          | value |
      | is_active     | false |
      | is_superuser  | true  |
      | is_verified   | true  |

  Scenario: Update a non-existent user
    When the administrator attempts to update a user that does not exist
    Then the system responds with a not found error

  # --- Deactivate / reactivate user ---

  Scenario: Deactivate a user
    Given a user account exists and is active
    When the administrator deactivates the user
    Then the user record is preserved with active set to false
    And the user can no longer access the system

  Scenario: Deactivate a non-existent user
    When the administrator attempts to deactivate a user that does not exist
    Then the system responds with a not found error

  Scenario: Reactivate a previously deactivated user
    Given a user account exists and is deactivated
    When the administrator reactivates the user
    Then the user record reflects active set to true
    And the user can access the system again

  Scenario: Deactivated user's past actions remain visible in the action trail
    Given a user account exists and is active
    And the user has submitted curation actions
    When the administrator deactivates the user
    Then all past curation actions by that user remain visible
    And each action is still attributable to the deactivated user

  Scenario: Cannot deactivate the last administrator
    Given only one active administrator account exists
    When the administrator attempts to deactivate that administrator account
    Then the system rejects the deactivation
    And the administrator account remains active

  # --- Current user ---

  Scenario: View current authenticated user
    When an authenticated user requests their own profile
    Then the response contains the user's email and role flags