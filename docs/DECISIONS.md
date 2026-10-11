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

## ADR-014 Defer RDFLib / PySHACL / LLM dependencies to the phase that uses them
**Status:** Accepted

**Decision.** Phase 1 installs only what it uses. RDFLib arrives with export/import (Phase 2),
PySHACL with fact validation (Phase 3), an OpenAI-compatible HTTP client with discovery (Phase 2).

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
