# Implementation Plan

Target: a demonstrable enterprise MVP in ~24 focused hours over three development days. Each
phase ends at a verified, runnable milestone that is safe to commit.

| Phase | Theme | Status |
|---|---|---|
| 1 | Application foundation & ontology designer | **Complete - verified** |
| 2 | AI discovery & governance | Planned |
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

## Phase 2 - AI discovery & governance (Day 2)

**Goal:** documents → AI proposals → SME decisions → validated, immutable published versions.

1. **LLM integration** - `LLMProvider` protocol with an OpenAI-compatible implementation
   (`OLS_LLM_BASE_URL`, `OLS_LLM_MODEL`, `OLS_LLM_API_KEY`); structured outputs validated with
   Pydantic; retries/timeouts; prompt templates versioned in code; recorded fixtures for tests.
2. **Source documents (minimal)** - upload/register text and PDF sources for discovery
   (`DocumentParser` protocol; chunk ids and page locations kept as evidence references).
3. **Discovery** - seed-ontology generation from documents; gap analysis of documents against the
   current draft; proposals of type *add class / add property / modify / alias / reuse /
   conflict*, each with rationale and evidence spans. Proposals are validated with
   `validate_schema` on a simulated draft before review.
4. **Change proposals & SME review** - `change_proposals`, `proposal_evidence`,
   `review_decisions`, `review_comments` tables; review queue, old-vs-proposed diff, edit before
   decision, approve / reject / request refinement; approved proposals applied through granular
   commands with full audit trail. Nothing is auto-approved.
5. **Registry & publishing** - `ontology_versions` (immutable canonical JSON snapshot, semantic
   version, content hash, published_by/at, release notes); `OntologyArtifactRepository`
   (filesystem) storing JSON and Turtle/OWL generated with RDFLib; publish only with a current
   error-free validation report; database-level immutability tests.
6. **Version comparison** - structural diff between two versions (added/removed/changed
   elements and fields) in API and UI.
7. **Import** - Turtle/OWL import via RDFLib into a draft (mapped to the canonical model).
8. **UI** - AI Discovery, SME Review and Registry tabs; workspace "pending reviews" and
   "published versions"; header shows the latest published version.

**Exit criteria:** an SME can generate proposals from a document, approve a subset, publish
v1.0.0, export Turtle, compare v1.0.0 with the draft, and the published version cannot be edited.

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
