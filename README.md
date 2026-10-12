# Ontology Lifecycle Studio

Human-governed, AI-assisted ontology engineering and knowledge-graph construction.

> **LLMs assist discovery. Domain experts govern meaning. Engineering systems enforce consistency.**

The studio treats an approved ontology as a long-lived enterprise asset: it is designed and
refined by domain experts, validated by deterministic rules, published as immutable versions and
then used to build knowledge graphs. The Supply Chain domain ships as demonstration data; nothing
in the application logic is specific to it.

| Lifecycle | Steps |
|---|---|
| Ontology governance | Create / import → AI-assisted discovery → SME review → validate → approve → publish → reuse & evolve |
| KG construction | Ingest → select approved ontology → extract → validate facts → build / refresh → evaluate → propose ontology improvements |

## Status - Phase 4 (verified)

| Capability | State |
|---|---|
| Project Workspace: create/select projects, ontology summary, validation status, pending reviews, published versions, data sources with preview, latest KG build, activity | ✅ working |
| **Project Lifecycle Navigator** (Phase 4): graphical, iteration-aware workflow; completed / reused / in-progress / pending / blocked / outdated per iteration, derived from real records; new iterations from any stage reusing earlier outputs; frozen history | ✅ working |
| Ontology Studio designer: visual graph, add/edit/delete classes, relationships, attributes, hierarchy, aliases, ontology settings | ✅ working |
| Draft persistence: atomic save, optimistic locking, revisions, layout, unsaved-changes guard | ✅ working |
| Structural validation: 24 issue codes, persisted reports, navigate from finding to element | ✅ working |
| **AI Discovery**: upload PDF/text sources, LLM analysis against the draft or a published version, evidence-grounded ADD / REUSE / ALIAS / MODIFY / CONFLICT proposals | ✅ working (any OpenAI-compatible LLM; verified with local Ollama `qwen2.5:7b`) |
| **Ontology alignment**: duplicate prevention, synonym and conflict detection, unknown-id rejection, dependency tracking | ✅ working (deterministic) |
| **SME Review**: evidence, current vs proposed, validation impact, edit, approve / reject / request refinement / reopen, comments, persistent review trail, apply approved changes to the draft | ✅ working (proposals from AI discovery and from KG feedback) |
| **Registry**: validation-gated publication of immutable versions, semantic versioning, history, comparison, Turtle / JSON export with checksums | ✅ working |
| **KG pipeline**: CSV + PDF sources, saved source-to-ontology mappings, published-version builds with ten persisted stages (nine for builds before Phase 4) and logs, history, rebuild | ✅ working |
| **KG extraction & validation**: deterministic record mapping, ontology-guided LLM extraction, entity resolution, independent structural and evidence validation → accepted / rejected / quarantined with reasons | ✅ working (verified with `qwen2.5:7b`) |
| **Graph**: provider-independent `GraphStore`, durable SQL adapter (Gremlin-shaped, build-scoped, idempotent), Cytoscape.js explorer with search, filters and source provenance | ✅ working (Cosmos DB Gremlin adapter **not** implemented - interface only) |
| **Evaluation & feedback**: metrics with explicit denominators, ontology gaps → SME proposals → new version → rebuild | ✅ working |
| **RDF / OWL** (Phase 4): persisted IRIs locked after publication, OWL semantics in the inspectors (equivalence, disjointness, restrictions, inverses, characteristics), lossless RDF import with preserved axioms, Turtle / RDF-XML / JSON-LD / N-Triples packages, OWL 2 RL reasoning preview | ✅ working |
| **SHACL** (Phase 4): generated, authored and preserved shapes, PySHACL validation without inference, versioned validation policies, per-fact SHACL lane; malformed shapes block publication | ✅ working |
| **Multi-graph deployments** (Phase 4): RDF and property-graph projections, compatibility reports, verified deployments to embedded Oxigraph and any SPARQL 1.1 endpoint, explorer read-back, read-only SPARQL console | ✅ working (Neo4j and Cosmos DB adapters **not** built - no server available; previews only) |
| **Settings** (Phase 4): LLM models and graph databases registered, tested for real and selected per project, run and build | ✅ working |

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the full plan and acceptance
criteria, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/DECISIONS.md](docs/DECISIONS.md) for architecture decisions.

## Technology

* **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite (PostgreSQL-compatible), RDFLib, owlrl, PySHACL, pyoxigraph, pypdf, httpx2, pytest
* **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix), React Flow, Cytoscape.js, TanStack Query, React Router
* **AI:** any OpenAI-compatible Chat Completions endpoint (Ollama, OpenAI, Azure OpenAI, vLLM, LM Studio)
* **Graph:** canonical SQL property graph (Gremlin-shaped) plus verified deployments to embedded Oxigraph and SPARQL 1.1 endpoints (the `oxigraph` server CLI is a dev dependency used by tests)

## Prerequisites

* Python **3.12+**
* Node.js **20.19+** (tested with 24) and npm
* For the optional end-to-end check: Microsoft Edge or Google Chrome installed locally

## Run locally (Windows PowerShell)

Open two terminals in the repository root.

**1 - Backend API** (http://127.0.0.1:8000, docs at http://127.0.0.1:8000/docs)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

On first start the database (`backend/data/ontology_studio.db`) is created, migrated and seeded
with the Supply Chain project.

**2 - Frontend** (http://localhost:5173)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

> If PowerShell blocks `Activate.ps1`, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the interpreter directly:
> `.\.venv\Scripts\python.exe -m uvicorn ...`.

### Configuration

All configuration comes from environment variables (prefix `OLS_` for the backend). Copy
[.env.example](.env.example) to `.env` in the repository root and adjust as needed; every value
has a working default. No secrets are stored in the code.

### Enable AI discovery and document extraction (optional)

AI discovery and LLM extraction from documents need an OpenAI-compatible LLM endpoint. Without
one, the studio explains how to enable it and nothing is simulated (knowledge graphs can still be
built from structured CSV sources). For a fully local setup with [Ollama](https://ollama.com):

```powershell
ollama pull qwen2.5:7b
# .env in the repository root
#   OLS_LLM_BASE_URL=http://localhost:11434/v1
#   OLS_LLM_MODEL=qwen2.5:7b
```

Hosted models work the same way (`OLS_LLM_BASE_URL`, `OLS_LLM_MODEL`, `OLS_LLM_API_KEY`). Restart
the backend after changing `.env`; the provider status is shown in Ontology Studio → AI Discovery.
On CPU-only machines a 7B model needs several minutes per batch; larger models find more synonyms
and conflicts. A sample source document is provided in [samples/](samples/).

### Database operations

```powershell
cd backend
python -m app.cli migrate        # apply Alembic migrations
python -m app.cli seed           # load the demo project into an empty database
python -m app.cli seed-samples   # upload samples/supply-chain/*.csv|pdf into the demo project
```

Reset the demo data: stop the backend, delete `backend\data\ontology_studio.db*` and
`backend\data\artifacts` (published artifacts are read-only files), start it again.

## Tests and checks

```powershell
# Backend: API, persistence, validation, discovery, alignment, governance, registry, KG pipeline, graph store, migrations
cd backend
python -m pytest
python -m ruff check app tests

# Frontend: type check + production build, and lint
cd frontend
npm run build
npm run lint

# End-to-end checks (backend and frontend running; they change data - use a disposable database)
npm run e2e:journey           # Phase 1 designer journey
npm run e2e:governance        # Phase 2 journey with the configured REAL LLM (takes minutes on CPU)
npm run e2e:kg                # Phase 3 KG journey; the PDF uses the REAL LLM (E2E_KG_SKIP_PDF=1 for CSV only)
npm run e2e:semantic          # Phase 4 RDF/OWL import, reasoning, SHACL, policies and Settings (registers the local Ollama LLM)
npm run e2e:graphs            # Phase 4 multi-graph: Oxigraph deployment, a real Oxigraph SPARQL server, SPARQL console
npm run e2e:lifecycle         # Phase 4 lifecycle navigator: iterations, reused outputs, frozen history
# E2E_BROWSER_CHANNEL=chrome to use Chrome, E2E_HEADED=1 to watch
```

Automated backend tests replace the LLM with an explicit scripted test double; the governance
and KG E2E journeys use the configured model. Screenshots are written to `frontend/e2e/artifacts/`.

## Using the studio

1. **Project Workspace** - project overview, ontology statistics, validation status, pending
   reviews, published versions and activity.
2. **Ontology Studio → Ontology Designer** - edit the working copy visually; **Save draft** (Ctrl+S).
3. **Ontology Studio → AI Discovery** - upload source documents, choose the baseline (current draft
   or a published version), optionally give the model a focus, and start a run. Findings whose
   evidence cannot be found in the source are discarded and listed with the reason.
4. **Ontology Studio → SME Review** - set your reviewer name, inspect each proposal's evidence,
   alignment notes and validation impact, edit if needed, approve / reject / request refinement,
   comment, then **Apply approved to draft**.
5. **Ontology Studio → Validation** - validate the saved draft; `Show` opens the affected element.
6. **Ontology Studio → Registry** - review the publication preview, publish an immutable version,
   compare versions and download Turtle or JSON.
7. **Knowledge Graph Studio → Pipeline** - pick a *published* ontology version (its classes and
   relationships are listed), select or upload sources (CSV and PDF), configure a mapping for each
   CSV (preview, suggestion from column names, live validation), set extraction options, then
   **Start build** and follow the nine stages and the log. Use **Rebuild with** to build again with
   another published version; earlier builds stay unchanged and can be compared.
8. **Knowledge Graph Studio → Graph Explorer** - explore the persisted graph (search, class /
   relationship / source filters, table view); click a node or relationship to see its build,
   ontology version, validation checks and the source record or page text behind it.
9. **Knowledge Graph Studio → Fact Validation** - every candidate fact with its status, evidence
   and reasons (e.g. "Direction reversed …", "not established by any source record").
10. **Knowledge Graph Studio → Evaluation & Feedback** - quality indicators with their definitions,
    and ontology gaps; select gaps and **Create change proposals** to send them to SME Review.

### Demonstration (Supply Chain)

With an empty database (see *Database operations*) and Ollama configured:

1. Ontology Studio → Registry → publish **v1.0.0**.
2. Knowledge Graph Studio → upload `samples/supply-chain/suppliers.csv`, `products.csv`,
   `purchase_orders.csv`, `supply_relationships.csv` and `supplier-performance-review.pdf`
   (or run `python -m app.cli seed-samples`), configure each CSV mapping (accept the suggestion and
   save) and start the build (the PDF takes a few minutes on a CPU-only model).
3. Fact Validation: *Steel Bracket SB-200 → supplies → Contoso Metals GmbH* is **rejected**
   (reversed direction); *Fabrikam Plastics Inc → supplies → P-999* is **quarantined** (P-999 is not
   established by any record); LLM facts whose quotes cannot be found are quarantined.
4. Graph Explorer: click *Northwind Components Ltd → supplies → Hydraulic Pump HP-100* to see the
   two CSV rows (and usually the PDF passage) supporting it.
5. Evaluation & Feedback: select the gap **certified by** (Supplier → Auditor) → Create change
   proposals → SME Review shows *Add class 'Auditor'* and *Add relationship 'certified by'* →
   approve both → Apply → Registry → publish **v1.1.0**.
6. Knowledge Graph Studio → select build #1 → **Rebuild with v1.1.0** → add `auditors.csv` with
   its mapping → Start. The certification is now accepted; build #1 is unchanged; compare the builds
   in Build history.

The automated version of this scenario is `npm run e2e:kg`.

## Repository layout

```text
backend/    FastAPI modular monolith (app/modules/*), Alembic migrations, pytest suite
frontend/   React + Vite SPA (src/features/*), shadcn/ui components, E2E journey scripts
samples/    Discovery handbook; supply-chain/ CSV datasets and PDF for knowledge graph builds
docs/       ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, DECISIONS.md
```

## Known limitations (through Phase 3)

* No authentication, authorisation or multi-tenancy; reviewers identify themselves by name.
* Discovery and extraction quality depend on the model: a 7B local model paraphrases quotes and
  sometimes reverses relationships - such facts are quarantined or rejected (never repaired), so
  recall from documents is modest. Runs and builds execute as in-process background tasks (one
  discovery run per ontology and one KG build per project at a time); a restart fails running jobs.
* Graph storage uses the local SQL adapter; the Azure Cosmos DB Gremlin adapter is designed
  (same `GraphStore` protocol) but not implemented or verified. The explorer is sized for MVP
  graphs (up to a few thousand elements; larger graphs are truncated with filters).
* Structured sources are CSV/TSV uploads (up to 10,000 records per source); the Snowflake connector
  is an interface only. Mappings cover one entity per mapping row, single-column identifiers and
  relationships within a record (no joins across files other than by shared business keys).
* Evidence validation is lexical (quotes must be located verbatim and mention the entities);
  coreference and paraphrase are quarantined. Metrics are pipeline/structural indicators, not
  precision or recall.
* Source documents: text formats and text-based PDFs only (no OCR, no Office formats); originals
  are not retained - only extracted text and chunks.
* Proposals that reference classes added by other proposals must be applied together with or after
  them; editing a proposal does not re-compute its dependencies.
* No ontology import yet; exports are Turtle and JSON (no RDF/XML or SHACL shapes; no RDF export of
  the knowledge graph).
* Object properties support one domain and one range class; no inverse/transitive
  characteristics or qualified cardinalities.
* Concurrent editing uses optimistic locking (reload on conflict), not real-time collaboration.
* The repository is in a OneDrive-synchronised folder; excluding `node_modules`, `.venv` and
  `backend/data` from sync avoids file-locking issues.
