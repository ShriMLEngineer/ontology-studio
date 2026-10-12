# Implementation Plan

Target: a demonstrable enterprise MVP in ~24 focused hours over three development days. Each
phase ends at a verified, runnable milestone that is safe to commit.

| Phase | Theme | Status |
|---|---|---|
| 1 | Application foundation & ontology designer | **Complete - verified** |
| 2 | AI-assisted discovery & governance | **Complete - verified** |
| 3 | Knowledge-graph engineering, visualisation, evaluation & feedback | **Complete - verified** |

---

## Phase 1 - Application foundation & ontology designer (Day 1)

### Scope delivered

| Area | Delivered |
|---|---|
| Backend foundation | FastAPI app factory, `OLS_*` settings, error envelope, SQLAlchemy 2 models, Alembic initial migration, auto-migrate, CLI |
| Projects | List / create (with initial ontology) / read / update, activity trail |
| Ontology authoring | Ontology CRUD; class, object-property and datatype-property CRUD with preconditions; cascade delete |
| Draft persistence | Atomic whole-draft save with optimistic concurrency, change summaries, revision history in activity, layout persistence |
| Validation | 24 structural issue codes (errors / warnings / info), persisted runs bound to draft revisions, history API |
| Seed | Supply Chain Core ontology (11 classes, 12 relationships, 17 attributes) loaded into an empty DB |
| Frontend shell | Collapsible three-section sidebar, header with project selector, ontology revision and API status |
| Project Workspace | Stats, ontology summary with validation status, recent activity, quick actions, create project |
| Ontology Studio | Visual designer (React Flow), outline/search, inspectors, add/edit/delete classes, relationships, attributes, hierarchy, ontology settings, save/discard/reload, conflict handling, unsaved-changes guard, validation tab |
| KG Studio | Lifecycle shell with live prerequisites and clearly marked Phase 3 scope |

### Acceptance criteria (verified)

| # | User journey step | Verified by |
|---|---|---|
| 1 | Launch the application | E2E step 1 |
| 2 | Open the Supply Chain project | E2E step 2 |
| 3 | Navigate to Ontology Studio | E2E step 3 |
| 4 | See the seed ontology displayed visually | E2E step 4 (≥ 11 nodes, ≥ 12 relationship edges, ≥ 5 subclass edges) |
| 5 | Add a new class through the UI | E2E step 5 (+ no overlap with existing nodes) |
| 6 | Edit a class definition | E2E step 6 |
| 7 | Add a relationship between two classes | E2E step 7 (+ drag-to-connect step 8) |
| 8 | Save the ontology draft | E2E step 9 (revision +1) |
| 9 | Refresh the browser | E2E step 10 |
| 10 | Verify all changes are persisted | E2E step 11 (UI and API) · pytest `test_user_journey_changes_persist_across_restart` |
| 11 | Run basic structural validation | E2E step 12 · pytest validation API tests |
| 12 | Display validation results | E2E step 13 (+ navigate from finding to element) |

Quality gates: `pytest` (55 tests), `npm run build` (tsc + Vite), `npm run lint` (oxlint),
`npm run e2e:journey` (15 steps).

---

## Phase 2 - AI-assisted discovery & governance (Day 2)

**Goal:** documents → AI proposals → SME decisions → validated, immutable published versions.

### Milestones (each verified and committed)

| # | Milestone | Verification |
|---|---|---|
| 1 | LLM provider abstraction, source documents (text/PDF), migration `0002` with immutability triggers | Provider tests against a mock transport, upload/parse/chunk tests, migration up/down and drift check, trigger checks |
| 2 | Discovery pipeline, SME governance, registry (backend) | Unit tests for grounding, alignment, apply, diff, RDF; API tests with a scripted test double; two live runs against local Ollama |
| 3 | Phase 2 UI inside Ontology Studio | Type check, lint, build; Phase 1 E2E regression; Phase 2 governance E2E with the real LLM |

### Scope delivered

| Area | Delivered |
|---|---|
| LLM integration | `LLMProvider` protocol; legacy OpenAI-compatible provider plus registered OpenAI, Anthropic, Azure AI Foundry and Ollama adapters; Pydantic-validated structured output, typed/sanitized errors, provider-specific connection tests, secret-by-environment-variable references, and separate discovery/KG project defaults |
| Source documents | Upload (multipart, 10 MB) of txt/md/csv/tsv/json/pdf behind a `DocumentParser` protocol; SHA-256 de-duplication; paragraph-aware chunks with offsets and pages |
| AI discovery | Background runs against the draft or a published version with optional SME focus; batched, domain-independent prompts; progress, token usage and discarded findings recorded per run |
| Evidence grounding | Every quote located in the source (exact or strict fuzzy); exact source spans with context and offsets stored; ungrounded findings discarded with reasons |
| Ontology alignment | Duplicate prevention (ADD → REUSE/ALIAS), synonym capture, signature conflicts → CONFLICT, alias collisions, literal-range correction, invented-id rejection, naming-convention normalisation, merging, cross-proposal dependencies |
| SME review | Queue with filters; evidence, current vs proposed values, alignment notes, model rationale, live validation impact; edit (including type conversion), approve / reject / request refinement / reopen with mandatory comments, comments, persistent review trail with reviewer identity |
| Apply | Dependency-ordered, drift-checked application of approved proposals to the draft with per-proposal failure isolation; one draft revision per apply; published versions untouched |
| Validation | Existing engine reused for proposal impact, approval gating and the publication gate |
| Registry | Publication preview, validation-gated publish, semantic version suggestion and enforcement, canonical snapshot + hash, immutable versions (API, ORM, triggers, `RESTRICT` FK, write-once read-only artifacts with checksum verification), history, compare, Turtle/JSON export |
| UI | AI Discovery, SME Review and Registry tabs inside Ontology Studio; reviewer identity; header and workspace summaries; KG prerequisites aware of published versions. Navigation unchanged. |

### Acceptance criteria (verified)

| Requirement | Verified by |
|---|---|
| AI Discovery produces ADD, REUSE, MODIFY, ALIAS and CONFLICT proposals with evidence | `test_discovery_run_produces_grounded_aligned_proposals` (all five types); live Ollama runs; E2E steps 3-6 |
| Alignment minimises duplicates and identifies conflicts | `test_alignment.py` (duplicates, synonyms, signature conflicts, alias collisions, literal ranges, dependencies) |
| SME review: evidence, edit, approve/reject/refine, comments, apply to the draft | `test_governance_api.py`; E2E steps 6-10 |
| SME decisions and evidence persist | Review-trail assertions in API tests and E2E step 7; evidence survives document deletion (denormalised) |
| AI proposals never update published ontologies | `test_applying_proposals_after_publication_changes_only_the_draft`; E2E step 9 |
| Publication blocked by validation errors | `test_publish_is_blocked_by_validation_errors`; publish preview in E2E step 12 |
| Immutable published versions, history, comparison, RDF/Turtle export | `test_registry.py` (immutability at API, ORM, SQL trigger and FK level; tamper detection; RDF round trip); E2E steps 12-15 |
| Configurable LLM providers with Pydantic-validated structured output; no fabricated results | `test_llm_provider.py`, `test_llm_providers.py`, registry migration tests, `503 LLM_NOT_CONFIGURED` test; live Ollama runs |

Quality gates: `pytest` (127 tests), `ruff check`, `npm run build`, `npm run lint`,
`npm run e2e:journey` (15 steps), `npm run e2e:governance` (15 steps, real LLM).

### Deferred from the original Phase 2 outline

* Ontology **import** (Turtle/OWL → draft) and "generate a seed ontology from documents" for an
  empty ontology (discovery against an empty draft already proposes classes and relationships).
* AI-assisted refinement of a single proposal from SME feedback (refinement is SME-edited today).

---

## Phase 3 - Knowledge-graph engineering, visualisation, evaluation & feedback (Day 3)

**Goal:** sources + a published ontology version → validated, traceable facts → persisted,
explorable graph → quality indicators → ontology gaps fed back into SME review → new version →
rebuild.

### Pre-implementation findings

* Reusable: published snapshots (`OntologySnapshot`) as schema authority, Phase 2 source documents
  and page-aware chunks, `ground_quote`, `normalize_term`/`align_findings`, `persist_drafts`, the
  `LLMProvider` abstraction, the background-run pattern and the activity log.
* No graph database, Gremlin/Cosmos client, Neo4j or PySHACL in the environment → durable SQL
  graph adapter behind a Gremlin-shaped protocol (ADR-028) and deterministic structural validation
  (ADR-027). No orchestration framework → deterministic orchestrator (ADR-029).
* Migration `0003`: KG tables, graph tables and `change_proposals.origin` / `kg_build_id`
  (batch-altered on SQLite without losing evidence or events - tested).

### Milestones (each verified and committed)

| # | Milestone | Verification |
|---|---|---|
| 3.1 | Source connectors and CSV preview, generic mappings (validation, suggestion, CRUD), published-version enforcement, build configuration and readiness, migration `0003`, sample data | `test_kg_foundation.py`; migration data-preservation test |
| 3.2 | LLM extraction contract and prompt, deterministic mapping transform, entity resolution, structural and evidence validation, persisted candidate facts, nine-stage orchestrator | `test_kg_pipeline.py`, `test_kg_extraction.py` (scripted LLM), `test_kg_units.py` |
| 3.3 | `GraphStore` + `SqlGraphStore`, graph APIs with provenance, rebuild isolation | Graph store unit tests (idempotency, isolation, integrity); API tests |
| 3.4 | Evaluation metrics, ontology gaps, gap → SME proposal, build comparison | Gap → proposal → approve → publish v1.1.0 → rebuild API test |
| UI | Knowledge Graph Studio: Pipeline, Graph Explorer (Cytoscape.js), Fact Validation, Evaluation & Feedback; KG feedback in SME Review; workspace data sources and KG status | Type check, lint, build; Phase 3 E2E (structured-only and real LLM); Phase 1/2 E2E regression |

### Scope delivered

| Area | Delivered |
|---|---|
| Data sources | Reuses Phase 2 ingestion (PDF/text with pages, CSV/TSV). `StructuredSource` / `TextSource` connector protocols (Snowflake-ready); CSV records with row numbers and raw lines; column profiles with inferred XSD types; preview in KG Studio and Project Workspace; PDF chunks never span pages. |
| Mappings | Generic spec (fixed class or class column, identifier/label/alias columns, key namespace, reference-only entities, attribute → datatype property, relationships with fixed or column-provided predicate); validation against a version (errors / warnings); deterministic suggestion; saved and reusable. |
| Builds | Published versions only; readiness checks; frozen configuration snapshot; nine persisted stages with timing, counts and logs; history; rebuild with another version; comparison; interrupted-build recovery. |
| LLM extraction | Snapshot-constrained prompt, Pydantic `LLMExtractionResponse`, id/label resolution against the version, quote location in the source, unknown concepts → gaps (only with located evidence), validated outputs kept for audit. |
| Entity resolution | Business key, compatible-class key match, alias/label match to exactly one entity, ambiguity flagged, persisted decisions and mentions. |
| Fact validation | Independent structural, evidence and resolution checks; ACCEPTED / REJECTED / QUARANTINED with persisted reasons; reversal detected and never repaired; literal datatype checks; single-value conflicts quarantined. |
| Graph | `GraphStore` protocol; `SqlGraphStore` with idempotent upserts, build scoping, search, neighbourhood, provenance; only accepted facts stored. |
| Explorer | Cytoscape.js canvas, layout/fit/zoom, search, class / relationship / source filters, table fallback, details drawer with traceability and evidence. |
| Evaluation | Metrics with explicit numerator/denominator/definition; failure-reason breakdown; explicit statement that precision/recall are not measured. |
| Feedback | Gaps → aligned, evidence-backed pending proposals (`origin = kg_build`) in SME Review; dependency-linked class + relationship proposals; status shown back on the gap. |

### Acceptance criteria (verified)

| Requirement | Verified by |
|---|---|
| Select sources, choose an approved version, configure and save a build | `test_build_configuration_is_saved_and_checked_for_readiness`; E2E steps 2-5 |
| Draft / unpublished versions cannot be used | `test_only_published_versions_are_selectable` (`PUBLISHED_VERSION_REQUIRED`); E2E step 2 |
| Extracted facts visible with accepted / rejected / quarantined status and reasons | `test_kg_pipeline.py`, `test_kg_extraction.py`; E2E steps 6-8 |
| Reversed relationship rejected (never repaired) | `test_reversed_relationship_is_rejected_and_never_repaired`, LLM variant in `test_text_facts_are_validated_against_structure_and_evidence`; E2E step 7 |
| Inadequately evidenced fact quarantined | `test_relationship_to_an_unestablished_entity_is_quarantined`, unlocated / weak / ambiguous LLM facts; E2E step 8 |
| Persisted graph explorable; relationships traceable to sources | `test_graph_contains_only_accepted_facts_and_supports_exploration`, `test_duplicate_facts_merge_into_one_edge_with_multiple_provenance`; E2E steps 9-11 |
| Metrics with explicit definitions | `test_evaluation_metrics_state_denominators`; E2E step 12 |
| Gap → SME-reviewable proposal → approve → publish → rebuild without losing the earlier build | `test_gap_to_proposal_to_new_version_and_isolated_rebuild`; E2E steps 13-17 |
| Idempotent graph writes, rebuild isolation, version traceability | `test_kg_units.py` graph store tests; isolation assertions in API and E2E tests |
| LLM output normalisation, unsupported predicates, missing evidence, duplicates, ambiguity | `test_kg_extraction.py`, `test_kg_units.py` |

Quality gates: `pytest` (169 tests, 42 new for Phase 3), `ruff check`, `alembic check` (no drift),
`npm run build` (KG Studio is a lazily loaded chunk), `npm run lint`, `npm run e2e:journey`
(15 steps), `npm run e2e:governance` (15 steps, real LLM) and `npm run e2e:kg` (17 steps; with the
real `qwen2.5:7b` the PDF batch took ~6 minutes on CPU and produced 13 text facts - 6 accepted,
3 rejected (two reversed relationships), 4 quarantined (paraphrased or non-supporting quotes)).

### Deferred

* Azure Cosmos DB Gremlin adapter (protocol and mapping designed, ADR-028) and a Snowflake
  `StructuredSource` connector - no credentials or connectivity in this environment.
* SHACL shapes / RDF export of the knowledge graph; multi-column identifiers and cross-file joins in
  mappings; LLM-assisted evidence review for quarantined facts.

---

## Phase 4 - Standards-based semantics and database-agnostic knowledge graphs (Day 4)

**Goal:** RDF/RDFS/OWL modelling with stable IRIs, lossless RDF import/export, SHACL shapes and
PySHACL validation, OWL 2 RL reasoning kept separate from the other validation lanes, database-
independent graph projections with verified deployments and compatibility reports, a Settings
section for LLM models and graph databases, and an iteration-aware Project Lifecycle Navigator -
without breaking Phase 1-3 data or behaviour. Baseline: the approved
[PHASE4_ARCHITECTURE_PROPOSAL.md](./PHASE4_ARCHITECTURE_PROPOSAL.md) (decisions D1-D11).

### Milestones (each verified and committed)

| # | Milestone | Verification |
|---|---|---|
| 4.1 | Persisted IRIs (minted, follow renames until published, then locked); OWL semantics per element; ontology header; `ols-semantic/2` serializer and package (Turtle, RDF/XML, JSON-LD, N-Triples, manifest); lossless RDF import with preserved extension axioms; OWL 2 RL entailment preview; migration `0004` | `test_semantics.py` (round trips, losslessness, IRI locking, migration backfill); `e2e:semantic` |
| 4.2 | SHACL shapes graph (generated, signature, authored, preserved); PySHACL engine without inference; SHACL-SHACL meta-check; shapes in the package; versioned validation policies (`application-strict/1` default = Phase 3 outcomes); KG `shacl_validation` stage with per-fact lanes; migration `0005` | `test_shacl.py` (policy parity 51/4/2, no RDFS inference, lanes); `e2e:semantic`, `e2e:kg` |
| Settings | Fourth navigation section; registered LLM models and graph connections (secrets by env-var name), real read-only connection tests, project defaults, selection at project creation, discovery and KG builds; migration `0006` | `test_settings.py`; `e2e:semantic` (real Ollama test) |
| 4.4/4.5 | Deterministic property-graph and RDF projections; capability and mapping profiles; compatibility reports with semantic-loss acknowledgement; adapters for local SQL, embedded Oxigraph and SPARQL 1.1 endpoints with verified counts; explorer read-back from deployments; read-only SPARQL console; migration `0007` with factual legacy rows | `test_graph_deployments.py` (incl. a real `oxigraph serve` endpoint and outage); `e2e:graphs` |
| Lifecycle | Project iterations with nine stages and six derived statuses, start from any stage reusing earlier outputs, frozen history; migration `0008` | `test_lifecycle.py`; `e2e:lifecycle` |
| 4.3 | Inspector *Advanced semantics* (equivalence, disjointness, restrictions, inverse, sub-properties, characteristics, functional, deprecation, language), IRI-lock and preserved-axiom badges, canvas marks, Validation tab lanes (SHACL well-formedness gate, OWL 2 RL check, evidence pointer) | `test_shacl.py` (shapes gate), `test_semantics.py` (locked ids); `e2e:semantic` steps 15-16 |

### Scope delivered

| Area | Delivered |
|---|---|
| Semantic model | Hybrid canonical model (D1): typed elements with persisted IRIs and OWL semantics plus preserved extension axioms for everything outside the profile; `required`/`multi_valued` become SHACL constraints, not OWL axioms (D2). |
| RDF | Export in four syntaxes; import into a new ontology or empty draft with an import report (modelled, preserved, superseded, added); blank-node reconciliation; preserved axioms anchored to elements, orphan detection blocks publication. |
| SHACL | Form editor for authored shapes, generated shapes from data constraints and signatures, imported SHACL preserved, sample-data validation, `shapes.ttl` in every new package, well-formedness gate at publication. |
| Validation lanes | Structural (model rules, gate), SHACL (per fact under a versioned policy), OWL 2 RL (informational unless a policy says otherwise), evidence (per fact) - stored and shown separately. |
| Graphs | Canonical local SQL graph unchanged; deployments to embedded Oxigraph or any SPARQL 1.1 endpoint (named graphs for data, provenance and ontology), verified by reading counts back; compatibility per feature; explorer and SPARQL console over deployed data. |
| Settings | LLM models and graph databases registered once, tested for real, chosen per project / run / build; builds freeze their choices. |
| Lifecycle | Graphical, iteration-aware workflow in Project Workspace; statuses derived from records; new iterations from intermediate stages with recorded reused outputs. |

### Backward compatibility (verified)

* Migrations `0004`-`0008` are additive; each was exercised on populated databases (IRI backfill,
  legacy deployment rows for completed builds, iteration #1 for existing projects) and `alembic
  check` reports no drift.
* Legacy (`ols-snapshot/1`) versions stay immutable and are exported through the frozen Phase 3
  serializer; derived RDF/shapes downloads are labelled as derived.
* Phase 3 builds keep their nine stages and verdicts; under the default policy new builds reproduce
  the Phase 3 outcomes exactly (51 accepted, 4 rejected, 2 quarantined on the sample data).
* SME approvals, proposals, evidence, provenance and earlier builds are untouched; the three original
  navigation sections are unchanged and Settings is the only new section.

### Deferred / not available

* GraphDB, Apache Jena Fuseki and Azure Cosmos DB (Gremlin) deployments are implemented but not
  verified against live servers (none was available); they are labelled *adapter not live-tested* in
  Settings and in compatibility reports. Neo4j was verified against AuraDB 5.27. See
  [GRAPH_DATABASES.md](GRAPH_DATABASES.md). No integration is simulated.
* Custom (user-defined) mapping profiles - three built-in, versioned profiles only.
* Editing imported (preserved) SHACL in the form editor - preserved verbatim, removable.
* Validation policies are code-defined and versioned (no policy editor).
* The SPARQL console cannot cancel a long-running query on the embedded store (results are capped;
  HTTP endpoints use a timeout).

Quality gates: `pytest` (231 tests, 62 new in Phase 4), `ruff check`, `alembic check` (no drift), `npm run build`,
`npm run lint`, and on fresh databases `npm run e2e:semantic` (23 steps, real local LLM test), `e2e:graphs` (9 steps,
real Oxigraph SPARQL server), `e2e:lifecycle` (8 steps), `e2e:kg` (17 steps, structured sources, unchanged 51/4/2),
`e2e:journey` (15 steps) and `e2e:governance` (15 steps, real `qwen2.5:7b`: 8 findings, 8 proposals).
