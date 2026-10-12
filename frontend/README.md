# Ontology Lifecycle Studio - frontend

React 19 + TypeScript + Vite single-page application. See the repository [README](../README.md)
for setup and [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#5-frontend) for the design.

| Script | Purpose |
|---|---|
| `npm run dev` | Dev server on http://localhost:5173 (proxies `/api` to the backend) |
| `npm run build` | Type check (`tsc -b`) and production build |
| `npm run lint` | oxlint |
| `npm run e2e:journey` | Ontology designer user-journey check against a running stack |
| `npm run e2e:about` | Read-only check of the About page (navigation, lifecycle explorer, architecture map, technology filter) |

Source layout: `src/app` (router), `src/components` (layout, shared states, shadcn/ui),
`src/features` (projects, workspace, ontology, kg, settings, about), `src/lib` (API client, query keys, helpers).