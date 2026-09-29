# rdf config reader

I want now to implement a YAML reader for the RDF config file. The RDF config file will contain information about the entities, relations, and attributes that we want to extract from the text. The YAML reader will read this config file and create a data structure that we can use to guide our extraction process.

We shall thus create a Pydantic domain model first for each entity type and an adapetr that reads the YAML structure into each domain model.

I will give you an example of the RDF config file in YAML format:

```yaml
# Namespace prefix registry - used by rdf_mapper.py to resolve prefixed names in field paths
namespaces:
  epo:   "http://data.europa.eu/a4g/ontology#"
  org:   "http://www.w3.org/ns/org#"
  locn:  "http://www.w3.org/ns/locn#"
  cccev: "http://data.europa.eu/m8g/"
  dct: "http://purl.org/dc/terms/"
  adms: "http://www.w3.org/ns/adms#"

# Entity type mappings: entity_type_string -> rdf_type + field property paths
# Property paths use / as separator for multi-hop traversal.
# Field names must match entity_fields in resolver.yaml (legal_name, country_code).
entity_types:
  ORGANISATION:
    rdf_type: "org:Organization"
    fields:
      legal_name:   "epo:hasLegalName"
      country_code: "cccev:registeredAddress/epo:hasCountryCode"
      nuts_code: "cccev:registeredAddress/epo:hasNutsCode"
      post_code: "cccev:registeredAddress/locn:postCode"
      post_name: "cccev:registeredAddress/locn:postName"
      thoroughfare: "cccev:registeredAddress/locn:thoroughfare"

  PROCEDURE:
    rdf_type: "epo:Procedure"
    fields:
      identifier: "epo:hasID/epo:hasIdentifierValue"
      title:   "dct:title"
      description: "dct:description"      
      legalBasis: "epo:hasLegalBasis"
      procedureType: "epo:hasProcedureType"
      purpose_nature: "epo:hasPurpose/epo:hasContractNatureType"
      purpose_classification: "epo:hasPurpose/epo:hasMainClassification"
```

## Plan - execute one step a time using teh right agents (upon completion of a step log its results below):
* create the domain models in the rdf_mention_parser module for the entity types (Organisation, Procedure)
* create the adapter that reads and validates the models correctly
* create unit tests for each function/class
* write services that use the adaptersa and domain models to parse a config file
* implement then gherkin features in parser_configuration.feature
* implement now an rdf parser that uses the config to parse RDF mentions from text (Task 5 in the EPIC). The outcome shall be a JSON strucuture usable in the link curation app (the structural asusmptions will be hardcoded there, but not in the ERS).  

For tests use the: 
* fixture `sample_rdf_mapping` that contains the above YAML content as a string.
* fixtures like org_group1_file1 and proc_group1_file1 can be also used in uinit and featutre tests to provide sample config files on disk.

---
# execution log/outcome:

## ✅ Step 1 — Domain models (2026-03-18)

**Files created:**
- `src/ers/rdf_mention_parser/domain/exceptions.py` — `UnsupportedEntityTypeError(DomainError)`
- `src/ers/rdf_mention_parser/domain/rdf_mapping_config.py` — `EntityTypeConfig`, `RDFMappingConfig`
- `src/ers/rdf_mention_parser/domain/__init__.py` — re-exports all three

**Design decisions:**
- Generic approach retained (`EntityTypeConfig` holds `rdf_type: str` + `fields: dict[str, str]`). No concrete per-entity-type subclasses — new entity types require only a YAML change (EPIC constraint #7).
- `RDFMappingConfig` validates at construction time: prefixes in `rdf_type` and every property path segment must be declared in `namespaces`; `entity_types` and each `fields` map must be non-empty; property path segments must match `prefix:localName` pattern (rejects free strings and URL-style values).
- `resolve_entity_type(uri)` expands prefixed `rdf_type` values via `namespaces` and returns the matching `EntityTypeConfig`, or raises `UnsupportedEntityTypeError`.

## ✅ Step 2 — Adapter (2026-03-18)

**Files created:**
- `src/ers/rdf_mention_parser/adapter/rdf_mapping_config_reader.py` — `RDFConfigReader`
- `src/ers/rdf_mention_parser/adapter/__init__.py` — re-exports `RDFConfigReader`

**Design decisions:**
- Three static factory methods: `from_string(yaml_text)`, `from_file(path)`, `from_env_or_default()`.
- Env var `ERS_PARSER_CONFIG_PATH` overrides the bundled default at `resources/rdf_mapping.yaml`.
- Adapter is thin: all validation delegated to Pydantic; callers receive `ValidationError`, `FileNotFoundError`, or `yaml.YAMLError` unmodified.

## ✅ Step 3 — Unit tests (2026-03-18)

**Files created:**
- `tests/unit/rdf_mention_parser/domain/test_rdf_mapping_config.py` — 16 tests (TC-001, TC-002, TC-003 + structural edge cases)
- `tests/unit/rdf_mention_parser/adapter/test_rdf_mapping_config_reader.py` — 11 tests (from_string, from_file, from_env_or_default)

**Result:** 27/27 passing.

## ✅ Step 5 — Gherkin feature implementation (2026-03-18)

**File updated:**
- `tests/feature/rdf_mention_parser/test_parser_configuration.py` — all TODO stubs replaced with real implementations

**Scenarios covered (12/12 passing):**
- Load valid config — single type (4 ns, 1 type, 6 fields) and two types (4 ns, 2 types, 6 fields)
- Reject undeclared prefix — in field path, in rdf_type, in second segment of multi-hop path
- Reject structural problems — empty entity_types, empty fields, missing namespaces, invalid path syntax, URL-style path
- Resolve entity type URI — match returns EntityTypeConfig; unknown URI raises UnsupportedEntityTypeError

**Design decisions:**
- No service layer needed for this feature. Steps wire `RDFConfigReader.from_string()` + `RDFMappingConfig` directly.
- Inline building blocks (`_FOUR_NAMESPACES`, `_ORGANISATION_FIELDS_6`) kept in the step file — they are construction tools for invalid-config scenarios, not canonical fixtures. Promoted to shared fixture only if a third test suite needs them.
- Structural problem strings matched with `startswith` to tolerate `(e.g. "...")` parentheticals in the Examples table.
- `Then <resolution_outcome>` branched on keyword substrings (`"configuration is returned"` / `"unsupported entity type error is raised"`).

## 🔲 Step 4 — Services (decision: not needed for Task 4)
`MentionParserService` (Task 3 in the EPIC) covers the full parse flow. Config loading does not require a service wrapper.

---

# Task 3 / Refactor session — 2026-03-18

## ✅ SPARQL query refactor (`build_sparql_query`)

- Replaced string concatenation with `string.Template` (`_SPARQL_TEMPLATE` module-level constant).
- Removed `LIMIT 1` — the service guards against multiple entities explicitly.
- **rdflib quirk discovered:** when an entity exists but has no configured fields, rdflib returns 0 rows (not 1 all-None row). `has_entity_of_type` is therefore retained to distinguish `EntityTypeMismatchError` (entity absent) from `EmptyExtractionError` (entity present, no data). The plan's "SPARQL row count encodes all three states" assumption does not hold for rdflib.

## ✅ `MultipleEntitiesFoundError` added

- `domain/exceptions.py` — new `MultipleEntitiesFoundError(entity_type_uri, count)`.
- `domain/__init__.py` — exported in imports + `__all__`.
- Service raises it when `len(rows) > 1` (after type check, before empty check).
- Unit test class `TestMultipleEntitiesFound` added.

## ✅ Public service API

- `load_config()` — thin wrapper over `RDFConfigReader.from_env_or_default()`.
- `parse_entity_mention(content, content_type, entity_type, config)` — wires `RDFParserAdapter` + `MentionParserService` internally; entrypoints never instantiate the class directly.
- Both exported from `services/__init__.py`.
- `TestLoadConfig` (2 tests) and `TestParseEntityMention` (2 tests) added.

**All tests:** 44/44 passing (23 unit + 21 feature).