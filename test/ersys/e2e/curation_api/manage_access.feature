Feature: Manage Curator Access
  UC-W5 — Manage Curator Access (docs/AnnexeB-UseCases/ucw5.adoc)
  As an Admin managing the Link Curation application
  I want to grant, suspend, reactivate, and retire curator access for identified users
  So that only authorised individuals can perform curation actions and past records remain traceable

  Background: System is clean and the curation service is reachable
    Given the Curation API is reachable
    And the access registry contains no test curator accounts
    And the user action log is empty

  # ---------------------------------------------------------------------------
  # UC-W5 — Scenario 1: Grant curator access
  # Reference: docs/AnnexeB-UseCases/ucw5.adoc §Brief Description (1. Grant)
  # ---------------------------------------------------------------------------

  Scenario: Admin grants curator access to a new user — user can subsequently perform curation actions
    Given an identified user does not yet exist in the access registry
    When an Admin grants curator access to that user
    Then the access grant operation is accepted
    And the user is present in the access registry with an active curator role
    And that user can successfully submit a re-evaluation request using their credentials

  # ---------------------------------------------------------------------------
  # UC-W5 — Scenario 2: Suspend curator access
  # Reference: docs/AnnexeB-UseCases/ucw5.adoc §Brief Description (3. Suspend)
  # ---------------------------------------------------------------------------

  Scenario: Admin suspends an active curator — subsequent curation actions are rejected
    Given an identified user has active curator access in the access registry
    When an Admin suspends curator access for that user
    Then the suspension operation is accepted
    And the user's status in the access registry reflects the suspended state
    And a subsequent re-evaluation request submitted by that user is rejected with an authorisation failure

  # ---------------------------------------------------------------------------
  # UC-W5 — Scenario 3: Reactivate suspended access
  # Reference: docs/AnnexeB-UseCases/ucw5.adoc §Brief Description (4. Reactivate)
  # ---------------------------------------------------------------------------

  Scenario: Admin reactivates a previously suspended curator — curation actions succeed again
    Given an identified user has suspended curator access in the access registry
    When an Admin reactivates curator access for that user
    Then the reactivation operation is accepted
    And the user's status in the access registry reflects the active state
    And a subsequent re-evaluation request submitted by that user is accepted

  # ---------------------------------------------------------------------------
  # UC-W5 — Scenario 4: Retire access permanently — history preserved
  # Reference: docs/AnnexeB-UseCases/ucw5.adoc §Brief Description (5. Retire)
  # ---------------------------------------------------------------------------

  Scenario: Admin retires a curator permanently — user cannot act but past records are preserved
    Given an identified user has active curator access in the access registry
    And that user has previously submitted re-evaluation requests recorded in the user action log
    When an Admin retires curator access for that user permanently
    Then the retirement operation is accepted
    And the user cannot submit a re-evaluation request using their credentials
    And the existing user action log entries referencing that user are still present and unchanged
    And the cluster assignments and decision store content are not affected by the retirement

  # ---------------------------------------------------------------------------
  # UC-W5 — Minimal Guarantee: No partial state on access management failure
  # Reference: docs/AnnexeB-UseCases/ucw5.adoc §Minimal Guarantees
  # ---------------------------------------------------------------------------

  Scenario: Access management operation that fails leaves no partial or ambiguous access state
    Given an identified user has active curator access in the access registry
    When an Admin attempts an access modification that the system cannot process
    Then an error is returned to the Admin
    And the user's access state in the access registry is unchanged from before the operation
