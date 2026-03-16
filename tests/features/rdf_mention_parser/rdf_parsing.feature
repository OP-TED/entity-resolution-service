Feature: Parse RDF Entity Mention into JSON Representation
  As a service layer consumer of the RDF Mention Parser,
  I want valid RDF content parsed and configured fields extracted into a JSON representation,
  So that downstream components work with structured data regardless of the RDF serialisation format.

  Background:
    Given the parser is configured for ORGANISATION with 6 field mappings
    And the entity type URI is "http://www.w3.org/ns/org#Organization"

  Scenario Outline: Extract configured fields from valid RDF content
    Given an RDF payload in "<content_type>" format describing an Organisation with <present_count> of 6 configured fields present
    When the mention is parsed
    Then a JSON representation is returned with <present_count> extracted fields
    And the remaining <absent_count> configured fields are absent

    Examples:
      | content_type        | present_count | absent_count |
      | text/turtle         | 6             | 0            |
      | application/rdf+xml | 6             | 0            |
      | text/turtle         | 2             | 4            |
      | text/turtle         | 1             | 5            |

  Scenario: Ignore RDF triples not declared in the configuration
    Given an RDF Turtle payload describing an Organisation with all 6 configured fields and 3 additional properties not in the configuration
    When the mention is parsed
    Then a JSON representation is returned with 6 extracted fields
    And no additional fields beyond the configured mappings appear in the result

  Scenario: Extract fields from multi-hop property paths where intermediate nodes exist but leaf is absent
    Given an RDF Turtle payload where the Organisation has a registered address node but the post code property is absent
    When the mention is parsed
    Then a JSON representation is returned
    And the post_code field is absent from the result
    And the other address fields that are present are correctly extracted

  Scenario Outline: Handle content size boundaries
    Given an RDF Turtle payload whose byte size is "<size_description>"
    When the mention is parsed
    Then "<outcome>"

    Examples:
      | size_description       | outcome                          |
      | exactly 1 MB           | a JSON representation is returned |
      | 1 byte over 1 MB       | a content_too_large error is raised |

  Scenario Outline: Reject invalid input with the appropriate error
    Given "<invalid_input>"
    When the mention is parsed for entity type URI "<entity_type_uri>"
    Then a "<error_type>" error is raised

    Examples:
      | invalid_input                                                                        | entity_type_uri                         | error_type               |
      | a payload with content type "application/json"                                        | http://www.w3.org/ns/org#Organization   | unsupported_content_type |
      | an RDF Turtle payload with malformed syntax                                           | http://www.w3.org/ns/org#Organization   | malformed_rdf            |
      | a valid RDF Turtle payload describing a Person, not an Organisation                   | http://www.w3.org/ns/org#Organization   | entity_type_mismatch     |
      | a valid Organisation RDF but with none of the 6 configured fields present             | http://www.w3.org/ns/org#Organization   | empty_extraction         |
      | a valid RDF Turtle payload describing an Organisation                                 | http://example.org/unknown#PersonEntity | unsupported_entity_type  |
