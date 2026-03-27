Feature: Parser Configuration Loading and Entity Type Resolution
  As a service layer consumer of the RDF Mention Parser,
  I want the parser configuration loaded from YAML, validated at startup,
  and entity type URIs reliably resolved to their configuration entries,
  So that the parser only runs with a coherent, self-consistent configuration.

  Background:
    Given the parser configuration loader is available

  Scenario Outline: Load a valid parser configuration
    Given a YAML configuration with <namespace_count> namespace prefixes, <type_count> entity types, and <field_count> field mappings for "<entity_type>"
    When the configuration is loaded
    Then a parser configuration is created
    And it contains <namespace_count> namespace prefixes and <type_count> entity types
    And the "<entity_type>" entry has <field_count> field mappings each associating a name with a property path

    Examples:
      | namespace_count | type_count | entity_type  | field_count |
      | 4               | 1          | ORGANISATION | 6           |
      | 4               | 2          | ORGANISATION | 6           |

  Scenario Outline: Reject a configuration with an undeclared namespace prefix
    Given a YAML configuration where <location> uses prefix "<prefix>" not declared in namespaces
    When the configuration is loaded
    Then a configuration validation error is raised

    Examples:
      | location                                     | prefix |
      | a field property path                        | xyz    |
      | the rdf_type                                 | foo    |
      | the second segment of a multi-hop field path | unk    |

  Scenario Outline: Reject a configuration with structural problems
    Given a YAML configuration where "<structural_problem>"
    When the configuration is loaded
    Then a configuration validation error is raised

    Examples:
      | structural_problem                                                          |
      | entity_types is an empty map                                                |
      | the ORGANISATION entry has an empty fields map                              |
      | the namespaces section is missing entirely                                  |
      | a field value contains an invalid property path syntax (e.g. "not a path")  |
      | a field value uses double slashes in the property path (e.g. "epo://bad")   |

  Scenario Outline: Resolve an entity type URI to its configuration entry
    Given a parser configuration with ORGANISATION mapped to "org:Organization"
    When entity type URI "<entity_type_uri>" is resolved
    Then <resolution_outcome>

    Examples:
      | entity_type_uri                           | resolution_outcome                                      |
      | http://www.w3.org/ns/org#Organization     | the ORGANISATION entity type configuration is returned  |
      | http://example.org/unknown#PersonEntity   | an unsupported entity type error is raised              |
