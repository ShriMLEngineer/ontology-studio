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

## Status - Phase 2 milestone (verified)

| Capability | State |
|---|---|
| Project Workspace: create/select projects, ontology summary, validation status, pending reviews, published versions, activity | ✅ working |
| Ontology Studio designer: visual graph, add/edit/delete classes, relationships, attributes, hierarchy, aliases, ontology settings | ✅ working |
| Draft persistence: atomic save, optimistic locking, revisions, layout, unsaved-changes guard | ✅ working |
| Structural validation: 24 issue codes, persisted reports, navigate from finding to element | ✅ working |
| **AI Discovery**: upload PDF/text sources, LLM analysis against the draft or a published version, evidence-grounded ADD / REUSE / ALIAS / MODIFY / CONFLICT proposals | ✅ working (any OpenAI-compatible LLM; verified with local Ollama `qwen2.5:7b`) |
| **Ontology alignment**: duplicate prevention, synonym and conflict detection, unknown-id rejection, dependency tracking | ✅ working (deterministic) |
| **SME Review**: evidence, current vs proposed, validation impact, edit, approve / reject / request refinement / reopen, comments, persistent review trail, apply approved changes to the draft | ✅ working |
| **Registry**: validation-gated publication of immutable versions, semantic versioning, history, comparison, Turtle / JSON export with checksums | ✅ working |
| Data sources for KG, KG pipeline, fact validation, graph explorer, evaluation | ⏳ Phase 3 (page shows lifecycle and prerequisites) |

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the full plan and acceptance
criteria, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/DECISIONS.md](docs/DECISIONS.md) for architecture decisions.

## Technology

* **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite (PostgreSQL-compatible), RDFLib, pypdf, httpx2, pytest
* **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix), React Flow, TanStack Query, React Router
* **AI:** any OpenAI-compatible Chat Completions endpoint (Ollama, OpenAI, Azure OpenAI, vLLM, LM Studio)

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

### Enable AI discovery (optional)

AI discovery needs an OpenAI-compatible LLM endpoint. Without one, the AI Discovery tab explains
how to enable it and nothing is simulated. For a fully local setup with [Ollama](https://ollama.com):

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
python -m app.cli migrate     # apply Alembic migrations
python -m app.cli seed        # load the demo project into an empty database
```

Reset the demo data: stop the backend, delete `backend\data\ontology_studio.db*` and
`backend\data\artifacts` (published artifacts are read-only files), start it again.

## Tests and checks

```powershell
# Backend: API, persistence, validation, discovery, alignment, governance, registry, migrations
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
# E2E_BROWSER_CHANNEL=chrome to use Chrome, E2E_HEADED=1 to watch
```

Automated backend tests replace the LLM with an explicit scripted test double; the governance
E2E uses the configured model. Screenshots are written to `frontend/e2e/artifacts/`.

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
7. **Knowledge Graph Studio** - lifecycle overview and prerequisites (construction arrives in Phase 3).

## Repository layout

```text
backend/    FastAPI modular monolith (app/modules/*), Alembic migrations, pytest suite
frontend/   React + Vite SPA (src/features/*), shadcn/ui components, E2E journey scripts
samples/    Sample source documents for AI discovery
docs/       ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, DECISIONS.md
```

## Known limitations (through Phase 2)

* No authentication, authorisation or multi-tenancy; reviewers identify themselves by name.
* Discovery quality depends on the model: small local models rarely report synonyms or conflicts
  on their own (the deterministic alignment still prevents duplicates when they re-propose
  existing concepts). Runs execute as in-process background tasks, one per ontology at a time.
* Source documents: text formats and text-based PDFs only (no OCR, no Office formats); originals
  are not retained - only extracted text and chunks.
* Proposals that reference classes added by other proposals must be applied together with or after
  them; editing a proposal does not re-compute its dependencies.
* No ontology import yet; exports are Turtle and JSON (no RDF/XML or SHACL shapes).
* Object properties support one domain and one range class; no inverse/transitive
  characteristics or qualified cardinalities.
* Concurrent editing uses optimistic locking (reload on conflict), not real-time collaboration.
* The repository is in a OneDrive-synchronised folder; excluding `node_modules`, `.venv` and
  `backend/data` from sync avoids file-locking issues.
