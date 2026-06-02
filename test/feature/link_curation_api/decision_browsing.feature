Feature: Decision browsing and filtering
  As a curator
  I need to browse resolution decisions with filtering and search
  So that I can find decisions requiring my attention

  Background:
    Given the curator is authenticated and verified

  # --- Basic listing ---

  Scenario: List decisions with default parameters
    Given multiple decisions exist in the decision store
    When the curator requests the decision list
    Then a paginated list of decision summaries is returned
    And each summary includes the entity mention preview, current placement, and timestamps

  Scenario: All decisions are listed when no confidence filters are provided
    Given multiple decisions exist in the decision store
    When the curator requests the decision list without specifying confidence filters
    Then all decisions are returned

  # --- Filtering ---

  Scenario Outline: Filter decisions by confidence range
    Given decisions exist with varying confidence scores
    When the curator filters decisions with minimum confidence <min> and maximum confidence <max>
    Then only decisions within the confidence range are returned

    Examples:
      | min  | max  |
      | 0.0  | 0.5  |
      | 0.5  | 0.85 |
      | 0.0  | 1.0  |

  Scenario: Filter decisions by entity type
    Given decisions exist for entity types "Organization" and "Procedure"
    When the curator filters decisions by entity type "Organization"
    Then only decisions for "Organization" entities are returned

  Scenario Outline: Filter decisions by similarity range
    Given decisions exist with varying similarity scores
    When the curator filters decisions with minimum similarity <min> and maximum similarity <max>
    Then only decisions within the similarity range are returned

    Examples:
      | min  | max  |
      | 0.0  | 0.5  |
      | 0.5  | 1.0  |

  # --- Ordering ---

  Scenario Outline: Order decisions by different fields
    Given multiple decisions exist with different timestamps and scores
    When the curator requests decisions ordered by "<ordering>"
    Then the decisions are returned in the specified order

    Examples:
      | ordering             |
      | confidence ascending |
      | confidence descending|
      | created at ascending |
      | created at descending|
      | updated at ascending |
      | updated at descending|

  Scenario: Apply multiple filters simultaneously
    Given decisions exist for entity types "Organization" and "Procedure" with varying confidence scores
    When the curator filters decisions by entity type "Organization" with maximum confidence 0.7
    Then only decisions for "Organization" entities with confidence at or below 0.7 are returned

  # --- Search ---

  Scenario: Search decisions by entity mention text
    Given decisions exist linked to entity mentions with various names
    When the curator searches for "Acme"
    Then only decisions for entity mentions matching "Acme" are returned

  Scenario: Search with no matching results
    Given decisions exist in the store
    When the curator searches for "zzz_nonexistent_entity"
    Then an empty result set is returned

  # --- Entity type validation ---

  Scenario: Reject invalid entity type filter
    When the curator filters decisions by an unsupported entity type "BANANA"
    Then the request is rejected with a validation error mentioning valid entity types

  Scenario: List available entity types
    When the curator requests the list of available entity types
    Then the configured entity types are returned in sorted order

  # --- Pagination ---

  Scenario: Navigate through decisions with cursor pagination
    Given 50 decisions exist in the store
    When the curator requests decisions with a limit of 20
    Then 20 decision summaries are returned
    And a next cursor is provided for further results

  Scenario: All results fit within the requested limit
    Given 5 decisions exist in the store
    When the curator requests decisions with a limit of 20
    Then 5 decision summaries are returned
    And no next cursor is provided

  # --- Review state filter ---

  Scenario: List decisions pending review (no prior action against current placement)
    Given a decision exists with no user_action recorded since its current placement
    When I GET /api/v1/curation/decisions?reviewed=false
    Then the response includes that decision

  Scenario: Filter decisions already reviewed on current placement
    Given a decision with a user_action whose created_at is after its current placement
    When I GET /api/v1/curation/decisions?reviewed=true
    Then the response includes that decision

  Scenario: ERE re-integration returns a previously-reviewed decision to Pending
    Given a decision was reviewed at T1 and ERE re-integrated a new outcome at T2 advancing updated_at past T1
    When I GET /api/v1/curation/decisions?reviewed=false
    Then the response includes that decision

  Scenario: Omitting reviewed leaves the result set unchanged
    Given multiple decisions exist in the decision store
    When the curator requests the decision list
    Then a paginated list of decision summaries is returned

  # --- Cluster-size sort ---

  Scenario: Sort decisions by cluster size ascending
    Given multiple decisions exist in the decision store
    When the curator requests decisions ordered by "cluster size ascending"
    Then the decisions are returned in the specified order

  Scenario: Sort decisions by cluster size descending
    Given multiple decisions exist in the decision store
    When the curator requests decisions ordered by "cluster size descending"
    Then the decisions are returned in the specified order

  Scenario: Cluster-size sort combined with reviewed filter
    Given multiple decisions exist in the decision store
    When I request decisions with ordering "cluster_size" and reviewed "false"
    Then the response is 200 and results are present