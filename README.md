# Ontology Lifecycle Studio

**Human-governed, AI-assisted ontology engineering and knowledge-graph construction.**

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![RDF · OWL · SHACL](https://img.shields.io/badge/RDF%20%C2%B7%20OWL%20%C2%B7%20SHACL-supported-5B21B6)

> **LLMs assist discovery. Domain experts govern meaning. Engineering systems enforce consistency.**

Ontology Lifecycle Studio is a web application for building and governing ontologies and for
turning source data into validated, traceable knowledge graphs. It treats an approved ontology as
a long-lived enterprise asset: domain experts design and refine it, deterministic rules validate
it, the registry publishes it as an immutable version, and knowledge graphs are then built against
that version with every fact traceable to its source.

[Overview](#overview) · [Features](#features) · [Architecture](#architecture) ·
[Getting started](#getting-started) · [Configuration](#configuration) ·
[Walkthrough](#walkthrough) · [Testing](#testing) · [Documentation](#documentation) ·
[Known limitations](#known-limitations)

## Overview

| Principle | How the studio applies it |
|---|---|
| **LLMs assist discovery** | AI output only ever becomes *pending proposals* backed by quotes that are verified against the source. Invented ids are rejected; duplicate and conflicting suggestions are re-classified. |
| **Domain experts govern meaning** | Nothing changes the draft until a subject-matter expert (SME) approves and applies it. Published versions are immutable snapshots. |
| **Engineering systems enforce consistency** | Structural validation, SHACL shapes, evidence checks, optimistic locking, a validation gate on publication and an append-only audit trail. |

The workflow spans two connected lifecycles, shown as an iteration-aware navigator in every project:

| Lifecycle | Steps |
|---|---|
| Ontology governance | Create / import → AI-assisted discovery → SME review → validate → approve → publish → reuse & evolve |
| Knowledge-graph construction | Ingest → select approved ontology → extract → validate facts → build / refresh → evaluate → propose ontology improvements |

The Supply Chain domain ships as demonstration data; nothing in the application logic is specific
to it, so the studio works for any domain.

## Features

### Project Workspace and Lifecycle Navigator

* Create and select projects; see ontology statistics, validation status, pending reviews, published
  versions, data sources (with preview), the latest knowledge-graph build and recent activity.
* The **Project Lifecycle Navigator** is a graphical, iteration-aware workflow. Each stage is
  *completed*, *reused*, *in progress*, *pending*, *blocked* or *outdated*, derived from real
  records. Start a new iteration from any stage, reuse earlier outputs and keep history frozen.

### Ontology Studio

| Area | Capabilities |
|---|---|
| **Ontology Designer** | Visual graph editor for classes, relationships, attributes, hierarchy, aliases and ontology settings. Atomic draft saves with optimistic locking, revisions, persisted layout and an unsaved-changes guard. |
| **AI Discovery** | Upload PDF or text sources, analyse them against the draft or a published version and receive evidence-grounded **ADD / REUSE / ALIAS / MODIFY / CONFLICT** proposals. Works with any supported LLM. |
| **Ontology alignment** | Deterministic duplicate prevention, synonym and conflict detection, unknown-id rejection and dependency tracking between proposals. |
| **SME Review** | Inspect evidence, current vs proposed values and validation impact; edit, approve, reject, request refinement or reopen; comment; keep a persistent review trail; apply approved changes to the draft. Proposals also arrive from knowledge-graph feedback. |
| **Validation** | 24 structural issue codes with persisted reports; jump from a finding straight to the affected element. |
| **RDF / OWL** | Persisted IRIs (locked after publication), OWL semantics in the inspectors (equivalence, disjointness, restrictions, inverses, property characteristics), lossless RDF import with preserved axioms, Turtle / RDF-XML / JSON-LD / N-Triples export and an OWL 2 RL reasoning preview. |
| **SHACL Shapes** | Generated, authored and preserved shapes validated with PySHACL (without inference), versioned validation policies and a per-fact SHACL lane. Malformed shapes block publication. |
| **Registry** | Validation-gated publication of immutable, semantically versioned packages with history, comparison, checksummed downloads and write-once artifacts. |

### Knowledge Graph Studio

| Area | Capabilities |
|---|---|
| **Pipeline** | CSV and PDF sources, saved source-to-ontology mappings and builds bound to a published ontology version. Ten persisted stages with logs, history and rebuild. |
| **Extraction and fact validation** | Deterministic record mapping, ontology-guided LLM extraction and entity resolution. Independent structural, SHACL and evidence validation sorts every candidate fact into **accepted**, **rejected** or **quarantined**, always with reasons. |
| **Graph Explorer** | Cytoscape.js canvas with search, class / relationship / source filters, a table view and a drawer showing the build, ontology version, validation checks and the source record or page text behind every node and relationship. |
| **Evaluation and feedback** | Metrics with explicit denominators and ontology gaps that become SME proposals, then a new version and a rebuild. |
| **Deployments** | RDF and property-graph projections with compatibility reports, verified deployments (counts read back from the target), explorer read-back and a read-only SPARQL console. |

### Settings

A provider-aware registry of **LLM models** and **graph databases**: register, test for real,
enable or disable and set a default; select per project, discovery run and build. Credentials are
referenced by environment-variable *name* and never stored. See
[docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md) and [docs/GRAPH_DATABASES.md](docs/GRAPH_DATABASES.md).

### About

The **About** page in the sidebar is an interactive tour of the product: how the lifecycle works,
where each capability lives, how the system is built and which technologies it uses.

### Supported integrations

| Integration | Providers | Verification |
|---|---|---|
| LLM | OpenAI, Anthropic, Azure AI Foundry, Ollama and any OpenAI-compatible endpoint | Verified with a local Ollama `qwen2.5:7b` model |
| Graph store (canonical) | Local SQL property graph (Gremlin-shaped, build-scoped, idempotent) | Covered by the regular test suite |
| RDF store | Embedded Oxigraph, generic SPARQL 1.1 endpoints | Verified live against an Oxigraph SPARQL server |
| Property graph | Neo4j / AuraDB | Verified live against AuraDB |
| Other graph databases | Azure Cosmos DB for Apache Gremlin, Ontotext GraphDB, Apache Jena Fuseki | Implemented, **not** live-verified (labelled *Adapter not live-tested* in the UI) |

## Architecture

```mermaid
flowchart LR
  user([Ontology engineer / SME]) --> ui["React SPA<br/>Vite · TanStack Query · React Flow · Cytoscape.js"]
  ui -- "/api (JSON, multipart)" --> api[FastAPI modular monolith]
  api --> db[("Application database<br/>SQLite · PostgreSQL-compatible")]
  api --> artifacts[("Write-once artifact store<br/>JSON · OWL · SHACL")]
  api --> llm[["LLM providers<br/>OpenAI · Anthropic · Azure AI Foundry · Ollama"]]
  api --> graph[("Graph databases<br/>Local SQL · Oxigraph · Neo4j · Cosmos DB Gremlin · GraphDB · Fuseki · SPARQL")]
```

The backend is a modular monolith (router → service → repository / pure functions → ORM) with
framework-free functions for the critical logic. The frontend is a single-page application that
calls only real APIs; without a configured LLM, discovery and document extraction are disabled
rather than simulated.

| Layer | Technologies |
|---|---|
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix), TanStack Query, React Router |
| **Canvas and graph visualisation** | React Flow (`@xyflow/react`) for the ontology designer and lifecycle workflow; Cytoscape.js for the knowledge-graph explorer |
| **Backend** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite (PostgreSQL-compatible), httpx2 |
| **Semantics and validation** | RDFLib, owlrl (OWL 2 RL), PySHACL, pyoxigraph |
| **AI** | OpenAI, Anthropic and Azure AI Foundry SDKs, Ollama and any OpenAI-compatible Chat Completions endpoint; pypdf for PDF text |
| **Graph targets** | Neo4j driver, gremlinpython, SPARQL 1.1 over HTTP, embedded Oxigraph |
| **Quality** | pytest, ruff, oxlint, the TypeScript compiler and playwright-core end-to-end journeys |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and
[docs/DECISIONS.md](docs/DECISIONS.md) for the architecture decision records.

## Getting started

### Prerequisites

* Python **3.12+**
* Node.js **20.19+** (tested with 24) and npm
* Optional, for the end-to-end journeys: Microsoft Edge or Google Chrome installed locally
* Optional, for AI discovery and document extraction: an LLM endpoint (see [Enable AI](#enable-ai-discovery-and-document-extraction))

### Run locally

Clone the repository and open two terminals in its root.

**1 - Backend API** (http://127.0.0.1:8000, interactive API docs at http://127.0.0.1:8000/docs)

```powershell
# Windows PowerShell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

```bash
# macOS / Linux
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

On first start the database (`backend/data/ontology_studio.db`) is created, migrated and seeded
with the Supply Chain project.

**2 - Frontend** (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

> If PowerShell blocks `Activate.ps1`, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the interpreter directly:
> `.\.venv\Scripts\python.exe -m uvicorn ...`.

## Configuration

All configuration comes from environment variables (prefix `OLS_` for the backend). Copy
[.env.example](.env.example) to `.env` in the repository root and adjust as needed; every value
has a working default. No secrets are stored in the code, and `.env` is git-ignored.

### Enable AI discovery and document extraction

AI is optional. AI discovery and LLM extraction from documents need an LLM endpoint; without
one, the studio explains how to enable it and nothing is simulated (knowledge graphs can still be
built from structured CSV sources).

The recommended way is **Settings → LLM models**: register OpenAI, Anthropic, Azure AI Foundry,
Ollama or any OpenAI-compatible endpoint, test the connection and select it per project, discovery
run or build. Settings stores only the *name* of the environment variable that holds the API key;
define its value in `.env` or the server environment. For a fully local setup with
[Ollama](https://ollama.com), the environment default needs no registration:

```bash
ollama pull qwen2.5:7b
# .env in the repository root
#   OLS_LLM_BASE_URL=http://localhost:11434/v1
#   OLS_LLM_MODEL=qwen2.5:7b
```

Hosted models work the same way (`OLS_LLM_BASE_URL`, `OLS_LLM_MODEL`, `OLS_LLM_API_KEY`). Restart
the backend after changing the environment default; the provider status is shown in Ontology
Studio → AI Discovery. On CPU-only machines a 7B model needs several minutes per batch; larger
models find more synonyms and conflicts. A sample source document is provided in
[samples/](samples/).

### Database operations

```bash
cd backend
python -m app.cli migrate        # apply Alembic migrations
python -m app.cli seed           # load the demo project into an empty database
python -m app.cli seed-samples   # upload samples/supply-chain/*.csv|pdf into the demo project
```

Reset the demo data: stop the backend, delete `backend/data/ontology_studio.db*` and
`backend/data/artifacts` (published artifacts are read-only files) and start it again.

## Walkthrough

### Using the studio

1. **Project Workspace** - project overview, ontology statistics, validation status, pending
   reviews, published versions, activity and the lifecycle navigator.
2. **Ontology Studio → Ontology Designer** - edit the working copy visually; **Save draft** (Ctrl+S).
3. **Ontology Studio → AI Discovery** - upload source documents, choose the baseline (current draft
   or a published version), optionally give the model a focus, and start a run. Findings whose
   evidence cannot be found in the source are discarded and listed with the reason.
4. **Ontology Studio → SME Review** - set your reviewer name, inspect each proposal's evidence,
   alignment notes and validation impact, edit if needed, approve / reject / request refinement,
   comment, then **Apply approved to draft**.
5. **Ontology Studio → Validation** - validate the saved draft; `Show` opens the affected element.
6. **Ontology Studio → RDF / OWL and SHACL Shapes** - preview the OWL export, import an existing
   RDF ontology (constructs the designer cannot model are preserved verbatim), run the OWL 2 RL
   reasoning preview, and author or review SHACL shapes.
7. **Ontology Studio → Registry** - review the publication preview, publish an immutable version,
   compare versions and download Turtle, RDF/XML, JSON-LD, N-Triples or JSON packages.
8. **Knowledge Graph Studio → Pipeline** - pick a *published* ontology version (its classes and
   relationships are listed), select or upload sources (CSV and PDF), configure a mapping for each
   CSV (preview, suggestion from column names, live validation), set extraction options, then
   **Start build** and follow the ten stages and the log. Use **Rebuild with** to build again with
   another published version; earlier builds stay unchanged and can be compared.
9. **Knowledge Graph Studio → Graph Explorer** - explore the persisted graph (search, class /
   relationship / source filters, table view); click a node or relationship to see its build,
   ontology version, validation checks and the source record or page text behind it.
10. **Knowledge Graph Studio → Fact Validation** - every candidate fact with its status, evidence
    and reasons (e.g. "Direction reversed …", "not established by any source record").
11. **Knowledge Graph Studio → Evaluation & Feedback** - quality indicators with their definitions,
    and ontology gaps; select gaps and **Create change proposals** to send them to SME Review.
12. **Knowledge Graph Studio → Deployments** - deploy a completed build to a registered graph
    database, review the compatibility report and query RDF deployments with the read-only SPARQL
    console.

### Demonstration (Supply Chain)

With an empty database (see [Database operations](#database-operations)) and an LLM configured:

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

## Testing

```bash
# Backend: API, persistence, validation, discovery, alignment, governance, registry, KG pipeline, graph store, migrations
cd backend
python -m pytest
python -m ruff check app tests

# Frontend: type check + production build, and lint
cd frontend
npm run build
npm run lint

# End-to-end journeys (backend and frontend running; they change data - use a disposable database)
npm run e2e:journey           # ontology designer journey
npm run e2e:governance        # AI discovery and SME review with the configured REAL LLM (takes minutes on CPU)
npm run e2e:kg                # knowledge-graph journey; the PDF uses the REAL LLM (E2E_KG_SKIP_PDF=1 for CSV only)
npm run e2e:semantic          # RDF/OWL import, reasoning, SHACL, policies and Settings (registers the local Ollama LLM)
npm run e2e:graphs            # multi-graph: Oxigraph deployment, a real Oxigraph SPARQL server, SPARQL console
npm run e2e:lifecycle         # lifecycle navigator: iterations, reused outputs, frozen history
npm run e2e:about             # About page: navigation, lifecycle explorer, architecture map, technology filter (read-only)
# E2E_BROWSER_CHANNEL=chrome to use Chrome, E2E_HEADED=1 to watch
```

Automated backend tests replace the LLM with an explicit scripted test double; the governance
and knowledge-graph E2E journeys use the configured model. Screenshots are written to
`frontend/e2e/artifacts/`. The optional live Neo4j journey is described in
[docs/GRAPH_DATABASES.md](docs/GRAPH_DATABASES.md#verification).

## Repository layout

```text
backend/    FastAPI modular monolith (app/modules/*), Alembic migrations, pytest suite
frontend/   React + Vite SPA (src/features/*), shadcn/ui components, E2E journey scripts
samples/    Discovery handbook, an RDF ontology to import and supply-chain/ CSV datasets and PDF for knowledge-graph builds
docs/       Architecture, decision records, LLM provider and graph database guides
```

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Principles, system context, backend modules, data model, API reference and frontend design |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision records and their rationale |
| [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md) | Supported LLM providers, credentials and operational notes |
| [docs/GRAPH_DATABASES.md](docs/GRAPH_DATABASES.md) | Graph database registry, deployment adapters, network safety and verification status |
| [.env.example](.env.example) | Every environment variable with its default |

## Known limitations

* No authentication, authorisation or multi-tenancy; reviewers identify themselves by name.
* Discovery and extraction quality depend on the model: a 7B local model paraphrases quotes and
  sometimes reverses relationships - such facts are quarantined or rejected (never repaired), so
  recall from documents is modest. Runs and builds execute as in-process background tasks (one
  discovery run per ontology and one KG build per project at a time); a restart fails running jobs.
* Graph storage defaults to the local SQL adapter. Neo4j and Cosmos DB Gremlin deployments use the
  same `GraphStore` read protocol; GraphDB, Fuseki and Cosmos DB are not live-verified (see
  [docs/GRAPH_DATABASES.md](docs/GRAPH_DATABASES.md)). Property-graph targets store a projection of
  the accepted facts, not ontology axioms or SHACL shapes. The explorer is sized for graphs of up
  to a few thousand elements; larger graphs are truncated with filters.
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
* RDF import interprets a documented OWL profile conservatively; other constructs are preserved as
  axioms and re-exported unchanged, but cannot be edited in the designer.
* Object properties have exactly one domain and one range class (no union domains).
* Concurrent editing uses optimistic locking (reload on conflict), not real-time collaboration.
* Cloud-synchronised folders (OneDrive, Dropbox) can lock files; keep `node_modules`, `.venv` and
  `backend/data` out of synchronisation.
