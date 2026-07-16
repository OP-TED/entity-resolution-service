# Manual Testing Report

**Last updated:** 2026-06-10

## Testing progress
### resolution_cycle.http

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c10 | `full_cycle` · S1 · 1.1 — Resolve returns CANONICAL cluster id | POST /resolve returns 200 with `canonical_entity_id` + `status` | ✅ |
| c20 | `full_cycle` · S1 · 1.2 — Lookup after resolve | GET /lookup returns `cluster_reference.cluster_id` | ✅ |
| c30 | `full_cycle` · S2  · 2.1–2.2 — Idempotent replay | Two identical POSTs return the same `canonical_entity_id`; not sure why canonical id is not returned | ✅ |
| c40 | `full_cycle` · S2 · 2.3 — Lookup after replay | GET /lookup confirms single canonical assignment | ✅ |
| c50 | `full_cycle` · S3 · 3.1–3.3 — Batch resolve | Three mentions (2×ORGANISATION + 1×PROCEDURE) each return 200 | ✅ |
| c60 | `full_cycle` · S3 · 3.4 — Refresh-bulk (first call) | POST /refresh-bulk returns all 3 mentions in delta | ✅ |
| c70 | `full_cycle` · S3 · 3.5 — Refresh-bulk (second call) | POST /refresh-bulk returns empty delta (snapshot already set) | ✅ |
| c80 | `full_cycle` · S4 · 4.1–4.2 — Resolve + initial lookup | POST /resolve + GET /lookup confirm initial canonical cluster A | ✅ |
| c90 | `full_cycle` · S4 · 4.3–4.5 — Curation action | Login → list decisions → assign mention to cluster B → 204 | ✅ |
| c100 | `full_cycle` · S4 · 4.6 — Lookup after curation | GET /lookup confirms cluster updated to B after ERE reprocessing | ✅ |
| c110 | `full_cycle`  — Idempotency conflict detected when content changed | GET /lookup with the same id but different content  | ✅ |
| c120 | `full_cycle`  — unsupported entity type properly handled | /resolve raises an error | ✅ |

### clustering-simple.http

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c200 | `clustering-simple` · S1 · 1.1 — Submit m91 (seed) | POST /resolve for Nordic Infrastructure Consulting AB (SWE); expect 200 | ✅ |
| c210 | `clustering-simple` · S1 · 1.2 — Submit m92 (identical) | POST /resolve with same content as m91; expect 200 | ✅ |
| c220 | `clustering-simple` · S1 · 1.3 — Submit m93 (identical) | POST /resolve with same content as m91; expect 200 | ✅ |
| c230 | `clustering-simple` · S2 · 2.1 — Lookup m91 | GET /lookup returns cluster_A | ✅ |
| c240 | `clustering-simple` · S2 · 2.2 — Lookup m92 | GET /lookup returns same cluster_A as m91 | ✅ |
| c250 | `clustering-simple` · S2 · 2.3 — Lookup m93 | GET /lookup returns same cluster_A as m91 | ✅ |

### clustering.http

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c300 | `clustering` · S1 · 1.1 — Submit m1 (DEU seed) | POST /resolve for Stadt Osnabrück; expect 200 | ✅ |
| c310 | `clustering` · S1 · 1.2 — Submit m2 (DEU near-dup) | POST /resolve, JW~0.82 vs m1; expect 200 | ✅ |
| c320 | `clustering` · S1 · 1.3 — Submit m3 (FRA seed) | POST /resolve for Conseil départemental Haute-Garonne; expect 200 | ✅ |
| c330 | `clustering` · S1 · 1.4 — Submit m4 (FRA near-dup) | POST /resolve, JW~0.88 vs m3; expect 200 | ✅ |
| c340 | `clustering` · S1 · 1.5 — Submit m5 (extends DEU) | POST /resolve, JW~0.89 vs m2; expect 200 | ✅ |
| c350 | `clustering` · S1 · 1.6 — Submit m6 (extends FRA) | POST /resolve, JW~0.78 vs m3/m4; expect 200 | ✅ |
| c360 | `clustering` · S2 · 2.1–2.3 — Lookup DEU cluster | m1/m2/m5 all share cluster_A | ✅ |
| c370 | `clustering` · S2 · 2.4–2.6 — Lookup FRA cluster | m3/m4/m6 all share cluster_B | ✅ |
| c380 | `clustering` · S2 — Cross-cluster isolation | cluster_A ≠ cluster_B; country blocking rule enforced | ✅ |

### resolution_cycle_edge_cases.http and resolution_cycle_big_payload.http

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c500 | `edge-cases` · A1 — Whitespace-only source_id | POST /resolve with source_id=" "; expect 400 or stored as " " | ✅ |
| c510 | `edge-cases` · A2 — Very long source_id | POST /resolve with 200+ char source_id; expect 200 (no max-length constraint) | ✅ |
| c520 | `edge-cases` · A3 — Content at 1 MiB limit | POST /resolve with exactly 1 048 576-byte Turtle; expect 200 | ✅ |
| c530 | `edge-cases` · A4 — Content 1 byte over 1 MiB | POST /resolve with 1 048 577-byte content; expect 400 ContentTooLargeError | ✅ |
| c540 | `edge-cases` · A5 — content_type wrong case | POST /resolve with "TEXT/TURTLE"; expect 400 VALIDATION_ERROR | ✅ |
| c550 | `edge-cases` · A6 — content_type with media parameter | POST /resolve with "text/turtle; charset=utf-8"; expect 400 VALIDATION_ERROR | ✅ |
| c560 | `edge-cases` · B1 — Unknown entity type | POST /resolve with entity_type="PERSON"; expect 400 PARSING_FAILED | ✅ |
| c570 | `edge-cases` · B2 — Lowercase entity type | POST /resolve with "organisation"; expect 400 PARSING_FAILED | ✅ |
| c580 | `edge-cases` · B3 — Trailing space in entity type | POST /resolve with "ORGANISATION "; expect 400 PARSING_FAILED | ✅ |
| c590 | `edge-cases` · C1 — Invalid Turtle syntax | POST /resolve with unparseable Turtle; expect 400 PARSING_FAILED | ✅ |
| c600 | `edge-cases` · C2 — Empty Turtle graph | POST /resolve with valid prefix but no triples; expect 400 PARSING_FAILED | ✅ |
| c610 | `edge-cases` · C3 — XXE injection via RDF/XML | POST /resolve with DOCTYPE /etc/passwd entity; expect 400 PARSING_FAILED | ✅ |
| c640 | `edge-cases` · D1a+D1b — Idempotency conflict (content diff) | First POST 200; replay same triad with content +1 char → 422 IDEMPOTENCY_CONFLICT | ✅ |
| c650 | `edge-cases` · D2a+D2b — Idempotency conflict (whitespace) | First POST 200; replay with trailing whitespace → 422 or 200 depending on normalisation | ✅ |
| c690 | `edge-cases` · F1 — limit = 0 | POST /refresh-bulk; expect 400 VALIDATION_ERROR | ✅ |
| c700 | `edge-cases` · F2 — limit = -1 | POST /refresh-bulk; expect 400 VALIDATION_ERROR | ✅ |
| c710 | `edge-cases` · F3 — limit = 1001 | POST /refresh-bulk; expect 400 VALIDATION_ERROR | ✅ |
| c720 | `edge-cases` · F4 — limit = 1 (minimum valid) | POST /refresh-bulk; expect 200 with ≤1 mention | ✅ |
| c730 | `edge-cases` · F5 — Invalid continuation_cursor | POST /refresh-bulk with garbage cursor; expect 400 VALIDATION_ERROR | ✅ |
| c740 | `edge-cases` · G1 — GET /resolve (wrong method) | GET instead of POST; expect 405 Method Not Allowed | ✅ |
| c750 | `edge-cases` · G2 — POST /lookup (wrong method) | POST instead of GET; expect 405 | ✅ |
| c770 | `edge-cases` · G4 — POST /resolve with text/plain | Wrong Content-Type header; expect 422 | ✅ |
| c780 | `edge-cases` · G5 — Wrong JSON structure | POST /resolve with {"foo":"bar"}; expect 422 VALIDATION_ERROR | ✅ |
| c790 | `edge-cases` · G6 — Extra unknown fields | POST /resolve with injected extra fields; expect 200 (ignored by Pydantic) | ✅ |
| c800 | `edge-cases` · H1 — text/turtle (reference) | POST /resolve with text/turtle; expect 200 | ✅ |
| c810 | `edge-cases` · H2 — application/rdf+xml | POST /resolve; expect 200 (in allowlist) | ✅ |
| c820 | `edge-cases` · H3 — application/ld+json | POST /resolve; expect 400 (not in allowlist) | ✅ |
| c830 | `edge-cases` · H4 — text/n3 | POST /resolve; expect 400 (not in allowlist) | ✅ |
| c840 | `edge-cases` · H5 — application/n-triples | POST /resolve; expect 400 (not in allowlist) | ✅ |
| c850 | `edge-cases` · H6 — application/trig | POST /resolve; expect 400 (not in allowlist) | ✅ |
| c860 | `edge-cases` · H7 — application/json (plain JSON) | POST /resolve; expect 400 (not in allowlist) | ✅ |
| c870 | `edge-cases` · H8 — application/xml (plain XML) | POST /resolve; expect 400 (not in allowlist) | ✅ |


### resolution_cycle.http — combo scenarios (S5–S9)

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c900 | `full_cycle` · S5 · 5.1 — Lookup unknown triad | GET /lookup before any resolve; expect 404 MENTION_NOT_FOUND | ✅ |
| c910 | `full_cycle` · S5 · 5.2–5.3 — Resolve then lookup | POST /resolve → 200; GET /lookup returns same cluster_id | ✅ |
| c920 | `full_cycle` · S6 · 6.1–6.2 — First resolve + lookup (C1) | POST /resolve (content H1) → 200; GET /lookup returns C1 | ✅ |
| c930 | `full_cycle` · S6 · 6.3 — Idempotency conflict | POST /resolve (same triad, content H2) → 422 IDEMPOTENCY_CONFLICT | ✅ |
| c940 | `full_cycle` · S6 · 6.4 — Lookup after conflict (C1 unchanged) | GET /lookup → 200 with same C1 as c920; conflict did not corrupt decision | ✅ |
| c950 | `full_cycle` · S7 · 7.1–7.2 — Submit to two sources | POST /resolve (source A) + POST /resolve (source B) → 200 each | ✅ |
| c960 | `full_cycle` · S7 · 7.3 — Refresh-bulk source A isolation | POST /refresh-bulk (source=A) → delta contains only source A's mention | ✅ |
| c970 | `full_cycle` · S7 · 7.4 — Refresh-bulk source B isolation | POST /refresh-bulk (source=B) → delta contains only source B's mention | ✅ |
| c980 | `full_cycle` · S8 · 8.1–8.3 — Resolve 3 mentions | POST /resolve ×3 (same source) → 200 each | ✅ |
| c985 | `full_cycle` · S8 · 8.4 — Pagination page 1 | POST /refresh-bulk limit=1, cursor=null → 1 item, has_more=true | ✅ |
| c988 | `full_cycle` · S8 · 8.5 — Pagination page 2 | POST /refresh-bulk limit=1, cursor=C1 → 1 item, has_more=true | ✅ |
| c990 | `full_cycle` · S8 · 8.6 — Pagination page 3 (final) | POST /refresh-bulk limit=1, cursor=C2 → 1 item, has_more=false, snapshot advances | ✅ |
| c993 | `full_cycle` · S8 · 8.7 — Empty delta after snapshot advance | POST /refresh-bulk limit=100, cursor=null → empty delta | ✅ |
| c996 | `full_cycle` · S9 · 9.1 — Resolve m1 | POST /resolve (m1) → 200; establishes record for idempotency conflict in 9.2 | ✅ |
| c997 | `full_cycle` · S9 · 9.2 — Resolve-bulk mixed outcomes | POST /resolve-bulk: m1 conflict → IDEMPOTENCY_CONFLICT, m2 malformed → PARSING_FAILED, m3 → 200; envelope 207 | ✅ |
| c998 | `full_cycle` · S9 · 9.3 — Lookup-bulk after partial failure | POST /lookup-bulk: m1 found, m2 MENTION_NOT_FOUND (failed resolve leaves no record), m3 found | ✅ |
| c999 | `full_cycle` · S10 · 10.1–10.2 — Discard of uncorrelated ERE outcome | POST /push (unknown triad) → {"pushed":1}; GET /lookup → 404 MENTION_NOT_FOUND (no decision created) | ✅ |

### resolution_and_curation.http — curation feedback loop (S1–S4)

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c1000 | `curation` · S1 · S1.1 — Resolve | POST /resolve → 200/202 | ✅ |
| c1001 | `curation` · S1 · S1.2 — Inject initial ERE response (2 candidates) | POST /push with proposed_cluster_ids=[s1_c1, s1_c2] → {"pushed":1}; current_placement=s1_c1, candidates=[s1_c2] | ✅ |
| c1003 | `curation` · S1 · S1.3–S1.4 — Login + list decisions | Login → 200; GET /curation/decisions → decision_id and s1_cluster_b (=s1_c2) extracted via chaining | ✅ |
| c1005 | `curation` · S1 · S1.5 — Assign to s1_cluster_b | POST /curation/decisions/{id}/assign {cluster_id: s1_c2} → 204; ERE re-evaluation published | ✅ |
| c1007 | `curation` · S1 · S1.6 — Inject second ERE response confirming assignment | POST /push with proposed_cluster_ids=[s1_c2] → {"pushed":1}; current_placement updated to s1_c2 | ✅ |
| c1009 | `curation` · S1 · S1.7 — Lookup after assign | GET /lookup → 200 with cluster_id == s1_c2 | ✅ |
| c1040 | `curation` · S2 · S2.1–S2.3 — Resolve + login + list decisions | POST /resolve → 200; login; GET /curation/decisions → decision_id chained from canonical_entity_id | ✅ |
| c1045 | `curation` · S2 · S2.4 — Reject all candidates | POST /curation/decisions/{id}/reject → 204; ERE re-evaluation published with exclusions | ✅ |
| c1047 | `curation` · S2 · S2.5 — Inject ERE response with exclusions | POST /push with excluded_cluster_ids=[s2_candidate_0] → {"pushed":1}; fresh SHA-256 cluster generated | ✅ |
| c1050 | `curation` · S2 · S2.6 — Lookup after reject | GET /lookup → 200 with cluster_id ∉ {original candidates} | ✅ |
| c1060 | `curation` · S3 · S3.1–S3.2 — Bulk-accept with empty selection | Login → 200; POST /curation/decisions/bulk-accept {decision_ids:[]} → 400 or 422; no side effects | ✅ |
| c1070 | `curation` · S4 · S4.1–S4.3 — Resolve + login + list decisions | POST /resolve → 200; login; GET /curation/decisions → decision_id extracted via chaining | ✅ |
| c1080 | `curation` · S4 · S4.4 — Assign to cluster not in candidates | POST /assign {cluster_id: 64×0} → 400 InvalidClusterError; no UserAction written, no ERE message published | ✅ |
| c1090 | `curation` · S5 · S5.1–S5.2 — Login + stats filtered by entity type | Login → 200; GET /curation/stats?entity_type=ORGANISATION → 200 with registry + curation fields ≥ 0 | ✅ |
| c1095 | `curation` · S5 · S5.3 — Stats unfiltered | GET /curation/stats → 200; total_entity_mentions ≥ filtered value from S5.2 | ✅ |
| c1500 | `curation` · S6 · S6.1–S6.2 — Resolve + inject 2-cluster seed | POST /resolve → 200; POST /push → {"pushed":1}; current_placement=s6_c1, candidates=[s6_c2] | ✅ |
| c1510 | `curation` · S6 · S6.3–S6.4 — Login + list decisions before accept | Login → 200; GET /decisions → decision present; reviewed_since_placement=false; previous_review_count=0 | ✅ |
| c1520 | `curation` · S6 · S6.5 — Accept current placement | POST /decisions/{id}/accept (no body) → 204; ERE re-eval published with proposed_cluster_ids=[s6_c1] | ✅ |
| c1530 | `curation` · S6 · S6.6 — List decisions after accept | GET /decisions → reviewed_since_placement=true; previous_review_count=1 | ✅ |
| c1540 | `curation` · S6 · S6.7 — Inject confirming ERE response | POST /push proposed_cluster_ids=[s6_c1] → {"pushed":1}; reviewed_since_placement resets to false | ✅ |
| c1550 | `curation` · S6 · S6.8 — Lookup after accept | GET /lookup → cluster_id == s6_c1 (unchanged; accept re-confirmed placement) | ✅ |
| c1600 | `curation` · S7 · S7.1–S7.3 — Resolve + login + inject seed | POST /resolve → 200; login; POST /push → {"pushed":1}; decision created with reviewed_since_placement=false | ✅ |
| c1610 | `curation` · S7 · S7.4–S7.5 — reviewed_since_placement filter (initial state) | GET ?reviewed_since_placement=false → decision present; GET ?reviewed_since_placement=true → decision absent | ✅ |
| c1620 | `curation` · S7 · S7.6 — Reject (sets reviewed_since_placement=true) | POST /decisions/{id}/reject → 204 | ✅ |
| c1630 | `curation` · S7 · S7.7–S7.8 — reviewed_since_placement filter after action | GET ?reviewed_since_placement=true → decision present; GET ?reviewed_since_placement=false → decision absent | ✅ |
| c1640 | `curation` · S7 · S7.9 — Inject fresh ERE re-placement | POST /push (no proposed_cluster_ids → SHA-256 cluster) → {"pushed":1}; reviewed_since_placement resets to false | ✅ |
| c1650 | `curation` · S7 · S7.10–S7.11 — reviewed_since_placement filter after re-placement | GET ?reviewed_since_placement=false → decision present again; GET ?reviewed_since_placement=true → absent; previous_review_count==1 (lifetime, not reset) | ✅ |

### refresh_bulk_with_updates.http — delta after external ERE update

| # | Test Case | Description | Status |
|---|-----------|-------------|--------|
| c1100 | `refresh-bulk-updates` · Step 1 — Bulk resolve A, B, C | POST /resolve-bulk (A=req-001, B=req-002, C=req-003, same source) → 200/207 with initial cluster ids | ✅ |
| c1110 | `refresh-bulk-updates` · Step 2 — First refresh-bulk | POST /refresh-bulk → delta contains A, B, C; has_more=false; snapshot advances | ✅ |
| c1120 | `refresh-bulk-updates` · Step 3 — Second refresh-bulk (empty) | POST /refresh-bulk → empty delta (nothing changed since snapshot) | ✅ |
| c1130 | `refresh-bulk-updates` · Step 4 — Inject ERE responses for A and B | POST /push → {"pushed": 2}; Decision Store updated for A and B; C untouched | ✅ |
| c1140 | `refresh-bulk-updates` · Step 5 — Third refresh-bulk (A and B only) | POST /refresh-bulk → delta contains A and B with new cluster ids; C absent | ✅ |
| c1150 | `refresh-bulk-updates` · Step 6 — Lookup-bulk final state | POST /lookup-bulk → A and B have updated cluster ids (≠ step 1); C has original cluster id | ✅ |
