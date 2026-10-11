# Architecture Decision Records

Lightweight ADRs. Status values: *Accepted*, *Superseded*, *Proposed*.

---

## ADR-001 Modular monolith on FastAPI
**Status:** Accepted (Phase 1)

**Context.** Ten functional areas (authoring, discovery, governance, validation, registry,
extraction, fact validation, graph, evaluation, projects) must stay separable, but the MVP is
developed by a small team in ~24 hours and has no scaling requirement.

**Decision.** One FastAPI application with one package per module under `app/modules/`, each
layered as router → service → repository → ORM, with Pydantic contracts. No microservices.

**Consequences.** Simple deployment and transactions; module boundaries are enforced by
convention and an acyclic import graph. Extracting a module later requires replacing in-process
service calls with an API.

## ADR-002 SQLite now, PostgreSQL-compatible schema
**Status:** Accepted

**Decision.** SQLAlchemy 2.x + Alembic with SQLite for local development. Only portable types are
used (`String`, `Text`, `Integer`, `Boolean`, `JSON`, timezone-aware `DateTime`). A
`UTCDateTime` type guarantees aware UTC datetimes on SQLite. Constraint naming conventions make
batch migrations deterministic. SQLite runs with `foreign_keys=ON` and WAL.

**Consequences.** Switching to PostgreSQL requires only `OLS_DATABASE_URL` and a driver. The test
suite asserts that models and migrations do not drift.

## ADR-003 Canonical ontology model independent of ORM, UI, LLM and graph DB
**Status:** Accepted

**Decision.** `modules/ontology/domain.py` defines `ClassDefinition`, `ObjectPropertyDefinition`,
`DatatypePropertyDefinition` and `OntologySchema` as Pydantic models. Repositories map ORM rows to
this model; the React Flow designer adapts it for display; LLM output (Phase 2) will be parsed into
proposal contracts, never directly into the model.

**Consequences.** Validation, export (RDFLib) and proposal application operate on one model. The
model is schema-only; KG instance facts get their own model in Phase 3.

## ADR-004 Stable element ids separate from IRIs
**Status:** Accepted

**Decision.** Every class/property has an immutable `id` (unique per ontology) and an editable
`local_name` that forms the IRI (`namespace + local_name`). References (`parent_ids`,
`domain_id`, `range_id`) use ids.

**Consequences.** Renames never break references, proposals and change history can track an
element across edits, and the UI can create ids client-side (`cls_<12 hex>`). After publication
(Phase 2) IRI changes become explicit, governed changes.

## ADR-005 Permissive drafts, strict commands, validation as the publication gate
**Status:** Accepted

**Context.** Drafts are work-in-progress and will also receive imported ontologies and
AI-proposed content that may be inconsistent. Rejecting every inconsistent intermediate state
makes editing painful and hides problems instead of reporting them.

**Decision.**
* The whole-draft save (`PUT /draft`) accepts structurally inconsistent content (e.g. unknown
  domain ids, duplicate local names) but rejects unrepresentable content (schema violations,
  duplicate element ids).
* Granular commands enforce their own preconditions (references exist, unique local names,
  acyclic hierarchy, cascade required for referenced classes).
* The validation module reports inconsistencies; Phase 2 publication requires a current,
  error-free report.

**Consequences.** Cross-element references are not foreign keys. The designer and outline must
surface dangling elements (they do), and validation must stay comprehensive.

## ADR-006 Whole-draft save with optimistic concurrency
**Status:** Accepted

**Decision.** The designer edits a local working copy and saves it atomically with
`base_revision`. The service diffs incoming elements against stored rows (add/update/remove),
increments `draft_revision` only for semantic changes, and records a change summary in the
activity log. A stale `base_revision` returns `409 DRAFT_REVISION_CONFLICT`.

**Consequences.** Lost updates are impossible; users get explicit "reload latest" handling.
Concurrent fine-grained merging is out of scope for the MVP.

## ADR-007 Diagram layout is presentation metadata
**Status:** Accepted

**Decision.** Node positions live in `ontology_diagram_layouts` keyed by class id, outside the
ontology model. Layout-only saves do not create a draft revision and never appear in exports.

## ADR-008 Pure, persisted structural validation
**Status:** Accepted

**Decision.** `validate_schema` is a pure function with error/warning/info severities and stable
issue codes. Each run is stored with the draft revision it validated, so reports can be shown as
current or outdated. History is available via `GET /validations?limit=`; `/validations/latest`
returns 404 when nothing was validated (the UI uses the history endpoint to avoid error noise).

**Consequences.** The same rules can validate AI proposals before review and gate publication.
SHACL-based validation (PySHACL) is added for instance data in Phase 3.

## ADR-009 MVP modelling scope
**Status:** Accepted

**Decision.** Object properties have exactly one domain and one range class (maps cleanly to
labelled property-graph edges and Gremlin); classes may have multiple parents; datatype
properties use a fixed XSD subset (`string, integer, decimal, boolean, date, dateTime, anyURI`)
with `required` / `multi_valued` constraints.

**Consequences.** Union domains, inverse/transitive characteristics and qualified cardinalities
are deferred and can be added to the canonical model without breaking stored data.

## ADR-010 Append-only activity log
**Status:** Accepted

**Decision.** Every user-visible mutation stages an `activity_events` row in the same transaction
(project, ontology, event type, summary, structured details).

**Consequences.** Provides the "recent activity" view now and the base for governance audit
trails in Phase 2.

## ADR-011 Frontend state: TanStack Query + working-copy reducer
**Status:** Accepted

**Decision.** Server state uses TanStack Query; the ontology draft uses a reducer-based working
copy (`useDraftEditor`) whose actions mirror backend semantics (e.g. cascading class deletion).
Unsaved changes are guarded on navigation and refresh.

## ADR-012 React Flow with custom floating edges for the ontology designer
**Status:** Accepted

**Decision.** Class nodes are custom components listing attributes; edges attach to node
boundaries, separate parallel edges and draw loops for self-relationships. Drag-to-connect opens
a prefilled relationship dialog; deletion goes through the inspector with confirmation.

## ADR-013 Seed through services, only into an empty database
**Status:** Accepted

**Decision.** The Supply Chain ontology is plain data applied through `ProjectService` and
`OntologyService.save_draft`, on startup only when no projects exist (or via
`python -m app.cli seed`).

**Consequences.** Seed data obeys the same invariants as user data and never overwrites user
changes on restart.

## ADR-014 Defer PySHACL and graph dependencies to the phase that uses them
**Status:** Accepted (updated in Phase 3)

**Decision.** Each phase installs only what it uses. Phase 2 added RDFLib (export), pypdf (PDF
text), python-multipart (uploads) and httpx2 (LLM HTTP). Phase 3 adds only Cytoscape.js on the
frontend; it needed no new backend dependency (see ADR-027 for SHACL and ADR-028 for graph
storage).

## ADR-015 Tooling choices
**Status:** Accepted

* **shadcn/ui** (Radix base, Nova preset) components are vendored in `src/components/ui`; the
  `shadcn` package is a dev dependency (its build-time CSS is bundled). `npm audit` reports a
  `braces` advisory only in this CLI's dev tool chain; `npm audit --omit=dev` is clean.
* **oxlint** (scaffold default) for linting; `tsc -b` for type checking.
* **E2E**: `playwright-core` drives the locally installed Edge/Chrome, so no browser download is
  needed. The journey script mutates data and is meant for a disposable database.
* **Test client**: `httpx2`, as recommended by Starlette 1.x.

## ADR-016 Automatic migrations on startup (development default)
**Status:** Accepted

**Decision.** `OLS_AUTO_MIGRATE=true` applies Alembic migrations in the FastAPI lifespan for a
zero-step local start. Managed environments should set it to `false` and run
`python -m app.cli migrate` as a release step.

---

# Phase 2 decisions

## ADR-017 LLM access through a provider protocol and the OpenAI-compatible API
**Status:** Accepted (Phase 2)

**Decision.** The application depends on `LLMProvider.generate_structured(system, user, schema)`.
The only production implementation targets the OpenAI-compatible Chat Completions API, which
covers OpenAI, Azure OpenAI (v1), Ollama, vLLM and LM Studio. Structured output is requested with
`response_format` (JSON Schema by default, JSON mode or prompt-only as fallbacks) and always
re-validated with Pydantic; one repair prompt is sent on invalid output. Without
`OLS_LLM_BASE_URL` and `OLS_LLM_MODEL` the provider is absent and discovery returns
`503 LLM_NOT_CONFIGURED`. Automated tests inject an explicit scripted test double; the product
never fabricates model output. The HTTP client is `httpx2` (the client Starlette recommends), so
one HTTP library serves runtime and tests.

## ADR-018 The model suggests; deterministic engineering decides what becomes a proposal
**Status:** Accepted

**Context.** Small or local models confuse element kinds, invent ids, paraphrase quotes and
re-propose existing concepts.

**Decision.** A separate LLM contract (`LLMFinding`) is mapped into proposals only after:
evidence grounding (quotes must be located in the source; otherwise the finding is discarded),
alignment against the baseline (duplicates → REUSE/ALIAS, signature clashes → CONFLICT, literal
ranges → attributes, invented ids resolved by name or rejected) and merging of duplicates. Every
adjustment is recorded as an alignment note and the verbatim validated finding is stored.

**Consequences.** Recall depends on the model (larger models find more synonyms and conflicts), but
precision, traceability and duplicate prevention do not.

## ADR-019 Discovery runs as background jobs
**Status:** Accepted

**Decision.** Runs are queued (`202`) and executed by FastAPI background tasks with per-batch
progress; no database session is held during LLM calls. One active run per ontology; runs left
active by a restart are failed at startup. A malformed batch is skipped, a transport failure fails
the run.

**Consequences.** Works with slow local models (minutes per batch). A dedicated worker queue can
replace background tasks without changing the API.

## ADR-020 Proposals are field-level change sets with dependencies
**Status:** Accepted

**Decision.** ADD proposals carry a complete canonical element (with a pre-generated id so other
proposals can reference it); ALIAS/MODIFY/CONFLICT carry `{field: {before, after}}`; REUSE carries
nothing. Proposals referencing classes added in the same run record `depends_on`.
`apply_change` is a pure function: scalar fields are checked for drift (`before` must still hold),
list fields (aliases, parents) are merged.

**Consequences.** Proposals stay valid while the draft evolves, conflicts are detected precisely,
and the same function powers impact previews and application.

## ADR-021 Approval is gated by the validation engine; application is explicit
**Status:** Accepted

**Decision.** Every proposal shows the validation delta of applying it (dependencies first) to the
current draft. Approval is refused when the change cannot be applied or introduces error-severity
issues; reject and request-refinement require a comment. Approved proposals reach the draft only
through "Apply approved", which applies them in dependency order, isolates failures and increments
the draft revision once. Apply is disabled in the UI while the designer has unsaved changes.

## ADR-022 Immutable publication in four layers
**Status:** Accepted

**Decision.** (1) No mutation endpoints for versions; (2) SQLAlchemy `before_update`/`before_delete`
guards; (3) database triggers (SQLite and PostgreSQL) plus a `RESTRICT` foreign key so neither
direct SQL nor cascades can alter or remove versions; (4) write-once, read-only artifact files whose
SHA-256 is verified on every export. Publication requires a fresh, error-free validation, a content
change since the latest version and a strictly increasing semantic version.

**Consequences.** An ontology with published versions cannot be deleted. Corrections are published
as new versions.

## ADR-023 Canonical snapshots and RDFLib export
**Status:** Accepted

**Decision.** Published content is a canonical JSON snapshot (elements sorted by id) hashed with
SHA-256; Turtle is generated from it with RDFLib using OWL, RDFS, SKOS and DCTERMS, keeping stable
element ids as `dcterms:identifier` for future round-tripping. Semantic-version bumps are suggested
from a structural diff.

## ADR-024 Reviewer identity without authentication
**Status:** Accepted for the MVP

**Decision.** With no authentication in scope, reviewers enter their name once (stored in the
browser) and it is recorded as the actor on decisions, comments, applications and publications.
Replace with the authenticated principal when identity is introduced.

## ADR-025 Source documents are stored as extracted text
**Status:** Accepted

**Decision.** Uploads (text formats and PDF via pypdf, 10 MB limit) are parsed behind a
`DocumentParser` protocol, de-duplicated per project by SHA-256 and stored as text plus
offset/page-tracked chunks; the original file is not retained. Evidence stores its own quote,
context, document name and page, so deleting a document never removes review evidence.

---

# Phase 3 decisions

## ADR-026 Builds bind to one immutable published version
**Status:** Accepted (Phase 3)

**Context.** A knowledge graph is only as trustworthy as the schema it was validated against, and
drafts change continuously.

**Decision.** A KG build accepts only an `ontology_version_id` (drafts are refused with
`PUBLISHED_VERSION_REQUIRED`); the version row is referenced with `RESTRICT`. Starting a build
freezes a configuration snapshot (version and content hash, source hashes, mapping specs, LLM
provider/model/prompt version). Configuration is editable only before start; executed builds are
retained and cannot be deleted. A rebuild is a new build (linked by `parent_build_id`) and never
mutates an earlier build or its graph.

**Consequences.** Every fact, node and edge is traceable to one version and one build; comparing
builds across versions is meaningful.

## ADR-027 Deterministic per-fact structural validation instead of SHACL
**Status:** Accepted (Phase 3)

**Context.** The requirement is per-fact verdicts with explicit reasons (including "direction
reversed") against a published snapshot whose constraints are classes, subclass hierarchy,
domain/range and XSD datatypes. SHACL (PySHACL) validates whole RDF graphs and reports shape
violations that would then have to be mapped back to candidate facts; it adds a dependency and
does not detect reversal.

**Decision.** Implement structural validation as pure Python checks against `OntologyView`
(class/predicate existence and kind, references, identifiers, domain/range with inheritance,
literal datatypes) with one persisted check result per rule. Reversal is detected (the swapped
endpoints would satisfy the signature) and reported, but the fact is rejected and never repaired.

**Consequences.** Fast, explainable, unit-tested validation reusing the canonical model. SHACL
export remains possible later from the same snapshot if shapes become a requirement.

## ADR-028 Durable SQL graph adapter behind a Gremlin-shaped `GraphStore`
**Status:** Accepted (Phase 3)

**Context.** The enterprise target is Azure Cosmos DB (Gremlin API). No Neo4j, Gremlin or Cosmos
connection, credential or client library exists in the environment (checked: no settings, no
packages, ports 7687/7474/8182 closed).

**Decision.** Define a provider-independent `GraphStore` protocol (idempotent vertex/edge upserts,
fetch, search, neighbourhood, provenance, counts) and implement `SqlGraphStore` on the existing
database (`graph_vertices`, `graph_edges` keyed by `(graph_id, id)`). The data model is the
TinkerPop property graph: vertex label = class local name, edge label = property local name,
properties, plus `fact_ids`/`source_ids` provenance. `graph_id` (= build id) maps to a Cosmos
partition key. Vertex ids are stable hashes of class + business key; edge ids hash
(subject, predicate, object), so duplicates merge and provenance accumulates.

**Consequences.** Durable, transactional, testable graph persistence with no new infrastructure.
A Cosmos adapter implements the same protocol; Cosmos integration is **not** claimed until a real
connection is verified. The SQL adapter is sized for MVP graphs (thousands of elements).

## ADR-029 Deterministic orchestrator with persisted stages
**Status:** Accepted (Phase 3)

**Decision.** A plain Python workflow (`kg/orchestrator.py`) runs the nine stages in a FastAPI
background task, writing stage status, timings, counts and log lines in short independent
transactions, so the UI reports actual progress (completed stages and LLM batch numbers - no
synthetic percentages). Failures mark the stage and build failed and skip later stages; builds
running at shutdown are failed on startup. One active build per project. No Celery, Redis, Kafka
or LangGraph (none exist in the codebase and none are needed for this workload).

**Consequences.** Simple and observable. Long CPU-bound LLM batches occupy one worker thread; a
durable queue becomes appropriate when builds must survive restarts or scale out.

## ADR-030 Structured sources use deterministic, generic mappings
**Status:** Accepted (Phase 3)

**Decision.** Records are transformed by saved mappings that reference columns and ontology
element ids only (no business concepts, no LLM per row). Classes and predicates may be read from
columns (edge lists) and are resolved against the selected version; unknown values become gaps.
Entity mappings can be "reference only" (a foreign key that does not establish the entity).
Mappings are validated against the build's version at save time and again at start. A
column-name based suggestion is offered but always saved by an SME. Sources are read through the
`StructuredSource` protocol so a Snowflake connector can replace the CSV source.

## ADR-031 Evidence validation is separate from structure and conservative
**Status:** Accepted (Phase 3)

**Decision.** Evidence is evaluated independently of structural validity. Structured facts are
supported by their record; LLM facts need a quote located verbatim (or with strict fuzzy matching)
in the source chunk that mentions both entities (or contains the attribute value). Endpoints must
be established by a master record or a located mention - a key referenced by only one row is not.
Not located / weak evidence → QUARANTINED; no evidence → REJECTED. No LLM self-assessment is used:
a model judging its own extraction is not evidence.

**Consequences.** Coreference ("it supplies…") and paraphrase are quarantined rather than
accepted - a deliberate precision-over-recall trade-off that SMEs can review.

## ADR-032 Entity resolution never merges on similarity
**Status:** Accepted (Phase 3)

**Decision.** Merge by business key (class + key namespace + normalised identifier; text mentions
may match a compatible sub/superclass), then by exact normalised label or configured alias against
exactly one identified entity of a compatible class. Multiple candidates produce an ambiguous
entity whose facts are quarantined; no fuzzy or embedding similarity is used to merge.

## ADR-033 Ontology gaps feed the existing governance workflow
**Status:** Accepted (Phase 3)

**Decision.** Gaps (unknown classes, relationships, attributes, unmapped fields) are persisted per
build with evidence. On request they become ADD findings aligned against the ontology's current
draft (Phase 2 `align_findings`, so duplicates become REUSE/ALIAS) and are stored as pending
proposals with `origin = kg_build` and `kg_build_id` (migration `0003`). Selected relationship gaps
include the unknown classes they depend on, linked through proposal dependencies. Nothing is
applied or published automatically; a newly published version simply becomes selectable for the
next build.

## ADR-034 PDF chunks never span pages
**Status:** Accepted (Phase 3)

**Decision.** PDF text is chunked per page (`chunk_pages`), so each chunk - and every quote located
in it - carries an exact page number for provenance. Text formats keep paragraph-aware chunking.

## ADR-035 Hybrid semantic model: typed OLS Semantic Profile plus preserved axioms
**Status:** Accepted (Phase 4, decision D1 of the Phase 4 proposal)

**Decision.** The typed canonical model stays authoritative for the *OLS Semantic Profile*: named
classes and properties with persisted IRIs, labels/definitions/aliases (optionally language
tagged), `rdfs:subClassOf`, single domain and range, `rdfs:subPropertyOf`, `owl:inverseOf`,
property characteristics, `owl:equivalentClass/Property`, `owl:disjointWith`, deprecation and the
restrictions some/all/hasValue/min/max/exact (qualified or not). Everything else in an imported
document is stored verbatim as an **extension axiom** (N-Triples with its blank-node closure,
anchored to element ids, scope `ontology` or `shapes`) and re-exported unchanged. The importer
interprets conservatively, re-serialises the typed model and reconciles by blank-node component; a
final check verifies that the export contains every source triple except the documented
*superseded* version-header triples (`owl:versionInfo`, `owl:versionIRI`, `dcterms:issued`), so
an import can never silently drop semantics. Axioms whose anchors are deleted block publication
(`EXTENSION_AXIOM_ORPHANED`) until an SME removes them (audited) or restores the element.

## ADR-036 Required and single-value are data constraints, not OWL axioms
**Status:** Accepted (Phase 4, D2)

**Decision.** From snapshot format `ols.ontology-snapshot/2` the switches `required` and
`multi_valued` no longer produce `owl:minCardinality 1` / `owl:FunctionalProperty`; they are data
constraints validated with SHACL. OWL characteristics are emitted only when set explicitly
(`semantics.functional`, object-property characteristics). The frozen Phase 1-3 serialiser
(`registry/rdf.py`) is kept for legacy `/1` snapshots, and the first `/2` publication after a `/1`
version carries a *semantic profile change* note with the number of axioms no longer asserted.

## ADR-037 Persisted IRIs, locked after publication
**Status:** Accepted (Phase 4, D3)

**Decision.** Every element stores its IRI. New elements get `namespace + local_name`; unpublished,
automatically managed IRIs follow renames and namespace changes; explicit (imported) IRIs are kept;
IRIs of elements in the latest published version (legacy versions derive them) are locked
(`IRI_LOCKED`). Migration `0004` backfills drafts with exactly the IRI the Phase 1-3 serialiser
derived, so the first export after the upgrade denotes the same resources. A draft IRI that had
already diverged from the last publication before the upgrade is kept (not rewritten) and shown in
the publish diff. Clients that omit `iri`/`semantics` (Phase 1-3 payloads) keep the stored values.

## ADR-038 Version packages are artifacts of the immutable version row
**Status:** Accepted (Phase 4, D4; refines the proposal's separate package table)

**Decision.** A `/2` publication writes, in the same transaction as the version row, write-once
artifacts for the snapshot JSON, OWL in Turtle, RDF/XML, JSON-LD and N-Triples, and a manifest
(`ols-semantic/2`: ontology/version IRI, prefixes, imports, content hash, artifact checksums,
preserved-axiom count). Storing the package in the existing immutable `artifacts` map avoids a new
table and keeps the four immutability layers unchanged. Legacy versions are reported as
`ols-semantic/1 (legacy)`; other RDF syntaxes are derived from their stored Turtle on export, flagged
with `X-Artifact-Derived: true` and never stored. SHACL shapes join the package in milestone 4.2.

## ADR-039 Reasoning is a separate, informational preview
**Status:** Accepted (Phase 4, D11)

**Decision.** `owlrl` (OWL 2 RL forward chaining) runs on a copy of the draft's OWL graph and reports
named-entity entailments and inconsistencies. Nothing is written back to the draft, a published
version or a graph target, and reasoning results are reported separately from structural
validation, SHACL validation and evidence validation.

## ADR-040 RDF import creates a new ontology or fills an empty draft
**Status:** Accepted (Phase 4, D10)

**Decision.** Imports never merge into a populated draft: they create a new ontology (name suffixed
when it collides) or fill an explicitly selected empty draft, whose namespace and prefix then come
from the document. Every import is recorded with file name, format, SHA-256, actor and the full
report (modelled, preserved, superseded and added triples, warnings). Properties without a single
declared domain/range are kept open; the ontology then uses `require_domain_range = false`, which
turns missing domain/range into warnings, and knowledge-graph checks treat an open signature as
admitting any class.

## ADR-041 SHACL shapes are generated, authored or preserved - and never inferred over
**Status:** Accepted (Phase 4.2; D4, D5)

**Decision.** The shapes graph of a draft or version combines generated constraint shapes (from
`required`, single value, datatype and range), generated signature shapes (domain/range, tagged
with their role), SME-authored node shapes (structured subset of SHACL Core edited in a form) and
imported SHACL kept verbatim. Publication materialises it into `shapes.ttl` in the version package.
PySHACL always runs with `inference="none"` and the ontology graph mixed in; a regression test proves
that RDFS inference would hide a reversed relationship. Imported SHACL is meta-validated
(SHACL-SHACL) and enforced but not reinterpreted into the form model.

## ADR-042 Validation policies are immutable, versioned definitions recorded per build
**Status:** Accepted (Phase 4.2; D5 - refines the proposal's policy tables)

**Decision.** Policies are code-defined with a versioned id (`key/version`); a build stores its
policy id in its settings and the complete policy configuration in its frozen configuration, so the
evaluation of every build stays reproducible even if later releases add policies or versions.
Changing a policy's meaning requires a new version. `application-strict/1` (default) reproduces
Phase 3 outcomes exactly; `shacl-signature/1` delegates domain/range to SHACL signature shapes;
`infer-and-flag/1` quarantines (never rejects) facts whose implied types are incompatible with the
asserted class or involved in an OWL 2 RL inconsistency.

## ADR-043 Validation lanes are stored separately per fact; earlier builds are not re-judged
**Status:** Accepted (Phase 4.2)

**Decision.** Structural, SHACL, entailment, evidence and resolution results are stored separately
(`kg_candidate_facts.lanes` for the Phase 4 lanes); the policy only decides how they combine into a
status, and checks relaxed by a policy are kept as information. New builds run ten stages; builds
created before Phase 4 keep their nine recorded stages, their facts keep `lanes = NULL` and the UI
labels them "not run".

## ADR-044 Instance IRIs use a frozen data namespace
**Status:** Accepted (Phase 4.2; D7)

**Decision.** Candidate entities are identified as `{data_namespace}e/{vertex_id}` in the RDF view
(and later in RDF graph targets). The data namespace is the project's `data_namespace` or, by
default, `{ontology IRI}/data/`; it is frozen in the build configuration at start.

## ADR-045 Settings is a fourth navigation section; configurations are global, defaults per project
**Status:** Accepted (Phase 4; user requirement)

**Decision.** LLM configurations and graph database connections are registered once and shared by
all projects; each project chooses defaults, and discovery runs and KG builds may override them.
The previous three-section navigation is extended by exactly one section, *Settings*. The
environment-configured LLM, the local SQL graph and the embedded Oxigraph store are virtual
built-ins, so existing installations keep working without configuration (existing projects get
NULL defaults, i.e. the built-ins).

## ADR-046 Secrets are referenced by environment variable; tests are real and read-only
**Status:** Accepted (Phase 4)

**Decision.** The database stores only the *name* of the environment variable that holds an API key
or password; values are read when a connection is opened and are never returned by the API.
Connection tests perform real, side-effect-free calls (`/models`, `SELECT count(*)`, opening the
embedded store, SPARQL `ASK`). Graph database kinds without a verified adapter (Neo4j, Cosmos DB
Gremlin) are listed as unavailable with the reason and cannot be registered; no integration is
simulated. Configuration changes are written to the server log and recorded on the record
(`updated_by`, `updated_at`); project default changes are project activity events.

