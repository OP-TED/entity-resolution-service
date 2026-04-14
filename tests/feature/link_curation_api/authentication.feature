Feature: Authentication
  As a user of the curation system
  I need to register, log in, and manage my session tokens
  So that I can securely access curation functionality

  # --- Registration ---

  Scenario: Register a new user account
    When a new user registers with a valid email and password
    Then the account is created successfully
    And the response contains the user's email and identifier

  Scenario: Register with an already used email
    Given a user account exists with email "taken@example.com"
    When another user attempts to register with email "taken@example.com"
    Then the registration is rejected without revealing whether the email exists

  Scenario Outline: Register with invalid password
    When a user attempts to register with a password of length <length>
    Then the registration is rejected as invalid

    Examples:
      | length |
      | 3      |
      | 200    |

  # --- Login ---

  Scenario: Log in with valid credentials
    Given a registered and active user exists
    When the user logs in with correct credentials
    Then the response contains an access token and a refresh token

  Scenario: Log in with wrong password
    Given a registered and active user exists
    When the user logs in with an incorrect password
    Then the login is rejected with an authentication error

  Scenario: Log in with non-existent email
    When a user logs in with an email that is not registered
    Then the login is rejected with an authentication error

  Scenario: Log in as an inactive user
    Given a registered user exists who has been deactivated
    When the user logs in with correct credentials
    Then the login is rejected because the account is deactivated

  # --- Token refresh ---

  Scenario: Refresh tokens with a valid refresh token
    Given a user has a valid refresh token
    When the user requests a token refresh
    Then a new access token and refresh token are returned

  Scenario: Refresh with an expired token
    Given a user has an expired refresh token
    When the user requests a token refresh
    Then the refresh is rejected with an authentication error

  Scenario: Refresh with an access token instead of a refresh token
    Given a user has a valid access token
    When the user attempts to refresh using the access token
    Then the refresh is rejected with an authentication error