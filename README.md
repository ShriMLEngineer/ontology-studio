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

## Status - Phase 1 milestone (verified)

| Capability | State |
|---|---|
| Project Workspace: create/select projects, ontology summary, validation status, activity, quick actions | ✅ working |
| Ontology Studio designer: visual graph, add/edit/delete classes, relationships, attributes, hierarchy, aliases, ontology settings | ✅ working |
| Draft persistence: atomic save, optimistic locking, revisions, layout, unsaved-changes guard | ✅ working |
| Structural validation: 24 issue codes, persisted reports, navigate from finding to element | ✅ working |
| AI discovery, SME review, registry / publishing / export, version comparison | ⏳ Phase 2 (tabs are labelled as planned) |
| Data sources, KG pipeline, fact validation, graph explorer, evaluation | ⏳ Phase 3 (page shows lifecycle and prerequisites) |

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the full plan and acceptance
criteria, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/DECISIONS.md](docs/DECISIONS.md) for architecture decisions.

## Technology

* **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite (PostgreSQL-compatible), pytest
* **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix), React Flow, TanStack Query, React Router

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

### Database operations

```powershell
cd backend
python -m app.cli migrate     # apply Alembic migrations
python -m app.cli seed        # load the demo project into an empty database
```

Reset the demo data: stop the backend, delete `backend\data\ontology_studio.db*`, start it again.

## Tests and checks

```powershell
# Backend: API, persistence, validation rules, seed and migration drift (55 tests)
cd backend
python -m pytest

# Frontend: type check + production build, and lint
cd frontend
npm run build
npm run lint

# End-to-end Phase 1 user journey (backend and frontend must be running).
# It edits the Supply Chain ontology, so use a disposable database.
npm run e2e:journey           # set E2E_BROWSER_CHANNEL=chrome to use Chrome, E2E_HEADED=1 to watch
```

The E2E script walks through the full journey (open project → designer → add class → edit
class → add relationship → save → refresh → verify persistence → validate → inspect results)
plus drag-to-connect, project creation and the unsaved-changes guard. Screenshots are written to
`frontend/e2e/artifacts/`.

## Using the studio

1. **Project Workspace** - project overview, ontology statistics, validation status and activity.
2. **Ontology Studio → Ontology Designer**
   * `+ Class` adds a class; the local name (IRI) is derived from the label.
   * Click a class to edit its definition, aliases, parent classes and attributes in the right drawer.
   * `Relationship`, or drag from a class's right handle onto another class, adds a relationship.
   * Edits are kept in a working copy until **Save draft** (Ctrl+S). Discard and Reload are available;
     concurrent edits are detected and never silently overwritten.
3. **Ontology Studio → Validation** - validates the saved draft; `Show` opens the affected element.
4. **Knowledge Graph Studio** - lifecycle overview and prerequisites (construction arrives in Phase 3).

## Repository layout

```text
backend/    FastAPI modular monolith (app/modules/*), Alembic migrations, pytest suite
frontend/   React + Vite SPA (src/features/*), shadcn/ui components, E2E journey script
docs/       ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, DECISIONS.md
```

## Known limitations (Phase 1)

* No authentication, authorisation or multi-tenancy (out of scope for the MVP).
* No ontology publishing, version history, comparison, import or export yet (Phase 2); the header
  therefore shows "No published version".
* AI discovery and SME review are not implemented (Phase 2); no LLM is called anywhere.
* Data sources and knowledge-graph construction are not implemented (Phase 3).
* Object properties support one domain and one range class; no inverse/transitive
  characteristics or qualified cardinalities yet.
* Concurrent editing uses optimistic locking (reload on conflict), not real-time collaboration.
* The working copy lives in the browser tab until saved; unsaved changes are protected by
  navigation and refresh prompts but are not auto-saved.
* The diagram has no automatic layout yet; new classes are placed at the nearest free spot.
* The repository is in a OneDrive-synchronised folder; excluding `node_modules`, `.venv` and
  `backend/data` from sync avoids file-locking issues during installs.
