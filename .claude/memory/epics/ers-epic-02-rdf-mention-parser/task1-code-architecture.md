#  create the robust guardrails for project code architecture with imporlinter


I want to create project level depndecy tracking and discipline in the .importlinter file. Thsi shall respect the cosmic python layered architecture and enforce no cyclic dependencies between layers, as well as other key architectural rules (e.g. no direct imports from ERE client to Decision Store, etc.).


On namig conventions:
- look at the tests/features folder structure, these will be the main packages found in the codebase, 
- in addition you will also consider the `commons` package which can be imported by any package, whcih represent system components (and each component can adderss various layers, e.g. domain + services + adapters)

Task: Produce a dependency-specification document for project architecture guardrails

You are not implementing `.importlinter` rules yet.
You are producing a precise dependency specification that will later be translated into Import Linter contracts.

Your output must be a human-reviewable architecture dependency spec in a simple proto-language.
Do not output `.importlinter` config.
Do not output Python code.
Do not silently invent dependencies.

Objective

Define robust architectural dependency guardrails for the Python project so that project-level import discipline can later be enforced automatically.

The architecture has two levels:
1. component packages at the system level
2. architectural layers inside each component package

The intended internal style is Cosmic Python style layering.

Primary inputs to inspect

Use these sources in this order of authority:
1. the system component dependency diagram
2. the internal layered architecture diagram
3. the actual Python package structure in the repository
4. the `tests/features` folder structure only as a supporting hint

Do not treat `tests/features` as the source of truth for package discovery.
Use the actual source tree as the source of truth.

What you must produce

Produce one dependency specification document with these sections, in this exact order:

1. Observed architecture
2. Assumptions
3. Component inventory
4. Layer model
5. Intra-component rules
6. Inter-component rules
7. Cross-cutting and shared package rules
8. Global prohibitions
9. Ambiguities requiring human confirmation

Required behavior before writing rules

First, describe what you see in the two diagrams in plain language.

Your description must explicitly distinguish:
- system components
- internal layers within a component
- arrows that indicate allowed dependencies/imports
- labels that indicate which layers exist inside a component

If the handwritten notes disagree with the diagrams, prefer the diagrams and call out the disagreement explicitly.

Component model

Treat each top-level business/system package as a component package.

A component package may contain any subset of these layer subpackages:
- entrypoints
- services
- adapters
- domain

Do not assume every component contains all four layers.
Only declare rules for layers that actually exist in that component.

There is also a shared package:
- commons

`commons` is a shared package, not a business component.
It may be imported by any component, but it must not become a backdoor that hides forbidden business-component dependencies.

Layer model to use

Inside each component, use this dependency direction:

Allowed:
- entrypoints may import services
- services may import domain
- services may import adapters
- adapters may import domain

Prohibited:
- domain must not import adapters
- domain must not import services
- domain must not import entrypoints
- adapters must not import services
- adapters must not import entrypoints
- services must not import entrypoints

Do not use reverse arrows in your writing.
Always express dependencies in one direction only, using “may import” or “must not import”.

State clearly that the intended result is an acyclic dependency graph inside each component.

Cross-cutting packages

If present as distinct component packages, treat these as cross-cutting:
- observability_adapter
- configuration_manager

Interpret cross-cutting as:
- any business component may import them if needed
- they must not import arbitrary business components unless the diagrams explicitly show that dependency

Do not assume bidirectional freedom.

Inter-component dependency rules

Write inter-component rules as direct allowed imports only.
Do not infer transitive dependencies as allowed direct imports.

Only include a direct dependency if:
- it is explicitly shown in the system diagram, or
- it is explicitly stated in the source material, and not contradicted by the diagram

Start with this candidate dependency set, but verify it against the diagrams before finalizing:

- ers_rest_api may import resolution_coordinator
- resolution_coordinator may import rdf_mention_parser
- resolution_coordinator may import ere_contract_client
- resolution_coordinator may import ere_result_integrator
- resolution_coordinator may import request_registry
- rdf_mention_parser may import request_registry
- rdf_mention_parser may import observability_adapter
- rdf_mention_parser may import configuration_manager
- ere_result_integrator may import resolution_decision_store
- link_curation_rest_api may import resolution_decision_store
- link_curation_rest_api may import user_action_store
- link_curation_rest_api may import user_store

You must explicitly verify and comment on whether the diagram also supports any of the following:
- link_curation_rest_api may import request_registry
- ers_rest_api may import rdf_mention_parser directly
- ers_rest_api may import ere_contract_client directly
- ers_rest_api may import ere_result_integrator directly
- ers_rest_api may import resolution_decision_store directly
- ere_contract_client may import resolution_decision_store
- resolution_coordinator may import observability_adapter

Do not include any of the above unless the diagram genuinely supports them.

Global prohibitions to include

State these principles explicitly:

1. No component may import another component unless that direct dependency is explicitly allowed.
2. No layer may import outward against the allowed layer direction.
3. No cycles are allowed within a component’s internal layer graph.
4. No cycles are allowed between component packages.
5. Entry-point-facing components such as REST APIs must not be imported by internal business components unless explicitly allowed by the diagrams.
6. Store-like components must only be imported by components explicitly shown to depend on them.
7. `commons` may be imported by any component, but must not be used to bypass forbidden business-component imports.

How to discover the real components

Inspect the source tree and map diagram labels to actual package names.

You must:
- identify actual top-level Python packages
- map diagram component names to those package names
- detect which of `entrypoints`, `services`, `adapters`, and `domain` exist in each component
- avoid inventing rules for non-existent packages or layers
- note all naming mismatches and unresolved mappings

The `tests/features` tree may help identify intended business capabilities, but it must not override the source tree.

Required output style

Write the final dependency specification using a simple proto-language like this:

component: resolution_coordinator
type: business_component
layers_present:
  - services
allowed_component_imports:
  - rdf_mention_parser
  - ere_contract_client
  - ere_result_integrator
  - request_registry
forbidden_component_imports:
  - resolution_decision_store
  - ers_rest_api
  - link_curation_rest_api
layer_rules:
  - services may import domain
  - services may import adapters
notes:
  - verify whether this component actually contains domain and adapters packages

Repeat that structure for every discovered component.

Then include shared/cross-cutting packages like this:

shared_package: commons
rules:
  - may be imported by any component
  - must not be used to bypass forbidden direct component imports

cross_cutting_package: observability_adapter
rules:
  - may be imported by any business component
  - must not import arbitrary business components unless explicitly allowed by the diagram

What not to do

Do not:
- generate `.importlinter` syntax
- generate code
- assume every component has all four layers
- reverse dependency direction
- infer transitive dependencies as allowed direct dependencies
- use `tests/features` as the sole architectural source
- silently resolve contradictions
- leave package-name assumptions undocumented

How to handle ambiguity

If the diagrams, notes, and source tree disagree, do not force a decision silently.

Instead, add an entry under “Ambiguities requiring human confirmation” with:
- the conflicting evidence
- the rule under interpretation A
- the rule under interpretation B
- your recommended interpretation
- the reason for the recommendation

Quality bar

The final dependency specification must be strict enough that another agent could later translate it into Import Linter contracts without guessing.

Your output must be:
- explicit
- directional
- non-ambiguous
- grounded in the diagrams and repository structure
- honest about uncertainty


- Important constraints:
- Be conservative.
- When in doubt, do not allow a dependency.
- Prefer explicit prohibition over vague wording.
- Prefer source-tree reality over assumed package layout.
- Record/report uncertainty instead of inventing architecture.