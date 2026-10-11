# Implementation Plan

Target: a demonstrable enterprise MVP in ~24 focused hours over three development days. Each
phase ends at a verified, runnable milestone that is safe to commit.

| Phase | Theme | Status |
|---|---|---|
| 1 | Application foundation & ontology designer | **Complete - verified** |
| 2 | AI-assisted discovery & governance | **Complete - verified** |
| 3 | Knowledge-graph construction & exploration | Planned |

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
| LLM integration | `LLMProvider` protocol; OpenAI-compatible provider (JSON Schema / JSON mode / prompt), `$ref` inlining for grammar engines, Pydantic validation with a repair attempt, typed transport/output errors, status endpoint with connectivity check; configuration only via `OLS_LLM_*` |
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
| Configurable LLM provider with Pydantic-validated structured output; no fabricated results | `test_llm_provider.py`; `503 LLM_NOT_CONFIGURED` test; live Ollama runs |

Quality gates: `pytest` (127 tests), `ruff check`, `npm run build`, `npm run lint`,
`npm run e2e:journey` (15 steps), `npm run e2e:governance` (15 steps, real LLM).

### Deferred from the original Phase 2 outline

* Ontology **import** (Turtle/OWL → draft) and "generate a seed ontology from documents" for an
  empty ontology (discovery against an empty draft already proposes classes and relationships).
* AI-assisted refinement of a single proposal from SME feedback (refinement is SME-edited today).

---

## Phase 3 - Knowledge-graph construction & exploration (Day 3)

**Goal:** documents/records + published ontology → validated facts → explorable, traceable graph.

1. **Data sources** - PDF and small structured datasets (CSV/JSON) per project; Snowflake
   connector interface stubbed for a later phase.
2. **Extraction runs** - choose sources and a *published* ontology version; schema-guided LLM
   extraction of entities and relationships into the normalised candidate-fact model (subject,
   predicate, object or literal, source location, evidence, ontology version, run id); deterministic
   mapping for structured records; run progress and logs.
3. **Entity resolution** - normalisation and alias-based merging with confidence and audit.
4. **Fact validation** - structural domain/range/datatype checks independent of the LLM (plus
   SHACL shapes generated from the ontology via PySHACL); evidence-grounding check as a separate
   dimension; facts accepted, rejected or quarantined with reasons; invalid directions are never
   auto-reversed.
5. **Graph persistence** - `GraphStore` protocol with a local implementation (SQLite tables /
   NetworkX) and a Cosmos DB Gremlin adapter behind configuration.
6. **Graph explorer** - Cytoscape.js view with search, class/relation/source filters, node/edge
   inspector and provenance back to source documents.
7. **Evaluation & feedback** - coverage and quality metrics, rejected-fact analysis, missing
   concept detection, and generation of ontology change proposals that enter the Phase 2 review
   queue.

**Exit criteria:** a KG build over the sample data shows accepted/rejected/quarantined facts with
reasons, the graph is explorable with provenance, and evaluation produces at least one ontology
improvement proposal visible in SME Review.
