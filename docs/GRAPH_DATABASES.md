# Graph database registry

Settings → **Graph databases** is a provider-aware registry. A *provider* describes one kind of graph
database (its connection fields, graph model, protocol and what the adapter can do); a *registration* is a
named, saved configuration of a provider. Several registrations of the same provider are allowed.

## Providers

| Provider | Graph model | Protocol | Connection test (read-only) | Deployment and Explorer read-back |
| --- | --- | --- | --- | --- |
| Azure Cosmos DB for Apache Gremlin (`cosmos-gremlin`) | Property graph | Gremlin over WebSocket, GraphSON 2 (`gremlinpython`) | `g.V().limit(1)` over an authenticated connection | Implemented — **not live-verified** |
| Neo4j / Neo4j AuraDB (`neo4j`) | Property graph | Bolt / Cypher (official `neo4j` driver) | `verify_connectivity()` plus `RETURN 1` in a read transaction on the configured database | Implemented — **live-verified against AuraDB 5.27** |
| Ontotext GraphDB (`graphdb`) | RDF | SPARQL 1.1 Protocol | SPARQL `ASK` on the derived or overridden query endpoint | Implemented through the generic SPARQL adapter — not live-verified against GraphDB |
| Apache Jena Fuseki (`fuseki`) | RDF | SPARQL 1.1 Protocol | SPARQL `ASK` | Implemented through the generic SPARQL adapter — not live-verified against Fuseki |
| Generic SPARQL 1.1 endpoint (`sparql-http`) | RDF | SPARQL 1.1 Protocol | SPARQL `ASK` | Implemented — **live-verified against the Oxigraph SPARQL server** |
| Local SQL Graph Store (`local-sql`) | Property graph | Internal adapter | `SELECT count(*)` on the application database | The canonical store; covered by the regular suite |
| Embedded Oxigraph (`oxigraph`, built in, not registrable) | RDF | Embedded `pyoxigraph` | Opens the embedded store | Covered by the regular suite |

Azure-hosted GraphDB is a *deployment* of GraphDB, not a separate API: register it as GraphDB with the
server URL of the Azure deployment. Existing generic SPARQL registrations are unchanged and keep working
(`kind = sparql-http`); a registration that has a user name but no authentication type is treated as HTTP basic.

A connection test verifies **connectivity and authentication only**. It never creates, changes or deletes
graph data, and says nothing about write permission or deployment readiness.

### Provider fields

* **Cosmos DB Gremlin** — account / Gremlin endpoint (account name, host or `wss://` URL), port (443),
  database, graph/container, partition-key path (single level, e.g. `/pk` or `/graphScope`), account key
  (environment-variable name), connection timeout. Plain `ws://` is accepted only for a local emulator.
* **Neo4j** — Bolt URI (`bolt`, `bolt+s`, `bolt+ssc`, `neo4j`, `neo4j+s`, `neo4j+ssc`), database, user name,
  password (environment-variable name), timeout. Public hosts require an encrypted scheme; `+ssc`
  (self-signed) is accepted only for private hosts.
* **GraphDB** — server URL, repository ID, optional query / update endpoint overrides (defaults
  `{server}/repositories/{id}` and `{server}/repositories/{id}/statements`), access (read-write or
  read-only), authentication: none, HTTP basic, bearer token or GraphDB token (`Authorization: GDB`).
* **Fuseki** and **generic SPARQL** — query endpoint, optional update endpoint (omit it for a read-only
  registration), authentication: none, basic or bearer.

The form is generated from the catalogue (`GET /settings/graph-kinds`): fields, defaults, option lists and
conditional visibility (for example the user name appears only for basic authentication) come from
`backend/app/modules/graph/targets/catalog.py`, and the API validates exactly what the form shows.

## Four different facts

The registry and Knowledge Graph Studio never collapse these into one "ready" flag:

| Fact | Meaning |
| --- | --- |
| **Registered** | The configuration exists and validated. |
| **Connected** | The last connection test succeeded (cleared when the endpoint or credential changes). |
| **Deployment supported** | The provider adapter can write and verify a build **and** this registration permits writes (a SPARQL registration without an update endpoint is read-only). |
| **Deployment verified** | A deployment to this registration was written and its counts read back from the target. |

*Adapter live-tested* is a separate, provider-level statement: whether the adapter has been exercised against
a real server of that provider (see [Verification](#verification)). `deployment_ready` additionally requires
the registration to be enabled and, for external databases, connected.

## Registry management

Register, edit, test, enable/disable, set a default, view status, and delete. Registrations persist in the
`graph_connections` table (migration `0010`).

* **Disable** stops new selection and deployments; historical deployments stay readable. A graph database
  that is a project default cannot be disabled or deleted until another is chosen.
* **Set default** preselects a registered, enabled, writable database for *new* projects only. Existing
  projects never change; the built-in local SQL graph is the implicit default.
* **Delete** removes only the registration. Recorded deployments stay readable (see below) and data already
  written to the database is not removed.

## Credentials and network safety

* Registrations store the **name** of an environment variable. The value is read from the server process
  environment, then the git-ignored `.env` files, only when a connection is opened. Values are never stored,
  returned by the API, written to logs or recorded in build/deployment snapshots; error messages are
  provider-specific and sanitised, and persisted deployment errors have any echoed credential replaced by `***`.
  Pasting a secret into a credential field is rejected without echoing it.
* Endpoints are validated at registration and again, with DNS resolution, at **every** connection, test or
  deployment (`backend/app/core/net_safety.py`): link-local, unspecified, multicast and reserved addresses and
  well-known cloud metadata addresses are always refused; URLs with embedded credentials or fragments are
  refused; public hosts must use TLS. Loopback and private addresses (a local Neo4j or Fuseki) are allowed
  unless `OLS_GRAPH_ALLOW_PRIVATE_NETWORKS=false`, which a shared server should set.
  Limits: the resolved address is not pinned to the connection (DNS rebinding between check and connect is not
  prevented by the application) and routed Bolt (`neo4j://`) follows the server's routing table; use network
  egress controls for strict isolation.

## Deployment adapters

All adapters deploy a build's projection through the existing mapping and capability profiles, **verify** the
deployment by reading counts back from the target, and record the outcome, the compatibility report and any
acknowledged semantic loss. A completed build can be deployed to any number of targets without repeating
extraction. A failing or unreachable target fails only its deployment; nothing falls back to another store.

* **RDF providers** (GraphDB, Fuseki, generic SPARQL) share `SparqlHttpAdapter`: `CLEAR` + `INSERT DATA` per
  named graph over the update endpoint (data, provenance, ontology), reads over the query endpoint. Only the
  authentication header differs between providers.
* **Neo4j** (`neo4j_store.py`): nodes carry the class label plus the marker label `OlsVertex`; every node and
  relationship has `_ols_scope` = the build id; system properties are namespaced `_ols_*`, so ontology
  attributes named `id` or `name` never collide. A deployment replaces its scope: it deletes only
  `OlsVertex` nodes of that scope, creates nodes and relationships in batches (`UNWIND`, values only as
  parameters, labels as escaped identifiers) and reads the counts back. Data outside the scope is never
  matched. A lookup index on `(OlsVertex._ols_scope, _ols_id)` is created best-effort. Lists must be homogeneous:
  mixed numeric lists are stored as floats, other mixed lists as strings.
* **Cosmos DB Gremlin** (`gremlin_store.py`): vertices carry the graph's partition-key property with the build
  id as value and are addressed with `g.V([partitionKey, id])`; values travel as bindings, labels and keys are
  reduced to `[A-Za-z0-9_]`; one request per element, concurrent in small windows, 429 responses retried after
  `x-ms-retry-after-ms`; scripts stay far below the 64 KB limit. Multi-valued attributes are kept exactly in a
  JSON property (single-valued ones are also plain properties). Search is evaluated on the fetched scope because
  case-insensitive containment is not a portable Gremlin predicate.

For a Cosmos graph created with partition-key path `/graphScope`, register exactly `/graphScope` in
Settings. Every deployed vertex receives `graphScope = <build id>`; both edge endpoints use that same
partition value. Scope deletion, counts, and Explorer reads use the configured key. An ontology attribute
named `graphScope` is renamed to `attr_graphScope` in the queryable projection and preserved under its
original name in the JSON attributes, so it cannot overwrite the build's partition value. Scripted-client
regressions cover `/graphScope` and the existing `/pk`, including writes for two build scopes and reads.
This verifies adapter behavior, not a live Cosmos deployment. The registration must match the existing
container's partition-key path; the read-only connection test does not validate that match. Each build
occupies one logical partition, so Cosmos logical-partition limits still apply to large builds.

Both property-graph stores implement the existing `GraphStore` read protocol, so the Graph Explorer (graph,
search, neighbourhood, element detail with provenance) behaves the same on every target. RDF and property
graphs stay distinct: there is no universal query language, the SPARQL console exists only for RDF
deployments, and a property-graph deployment is explored through the explorer.

### Historical isolation

Each deployment records a snapshot of the non-secret connection settings it was written with (provider,
configuration, credential *name*). Reads of that deployment use the snapshot, so editing, re-pointing or
deleting a registration never redirects or breaks historical deployments; new deployments use the current
registration. Build configuration snapshots likewise freeze the graph target (including `provider`) a build used.
Migration `0010` snapshots the current configuration onto existing deployments of registered targets.

## Adding a provider (for example TigerGraph)

1. Add a `TargetKind` to `catalog.py` (fields with types, defaults and visibility; model; protocol; capability
   flags) and its endpoint validation in `_validate_endpoints`.
2. Add a read-only probe and a branch in `SettingsService.probe_graph`.
3. If it can store graphs: implement `replace_scope` / `clear_scope` plus the `GraphStore` reads
   (`ReadableGraphStore` provides neighbourhood and provenance), register it in `property_graph_store`, add a
   `CapabilityProfile`, and set `deployment_supported` / `read_supported`.
4. Leave `live_tested = false` until it has been run against a real server.

The Settings UI, API schemas and Knowledge Graph Studio need no change.

## Verification

| Provider | Unit / API tests | Live server |
| --- | --- | --- |
| Neo4j / AuraDB | scripted-driver tests: read-only probe, scoped writes and deletes, escaping, error mapping, pooling | **Yes** — Neo4j AuraDB 5.27: connection test, deployment of a real KG build, driver read-back of the counts, Graph Explorer read-back, idempotent redeploy, scoped cleanup leaving all other data unchanged (`tests/test_live_neo4j.py`, `npm run e2e:neo4j`) |
| Generic SPARQL | integration tests against the Oxigraph SPARQL server | **Yes** — Oxigraph server |
| GraphDB, Fuseki | the same adapter and tests, registered under their own providers (authentication schemes checked against a recording server) | **No** — no GraphDB or Fuseki instance was available (the Oxigraph server stood in as a SPARQL 1.1 store) |
| Cosmos DB Gremlin | scripted-client tests: documented client settings (URL, `/dbs/…/colls/…` user, GraphSON 2), partitioned addressing, bindings, throttling retry, error mapping, element decoding | **No** — no Cosmos DB account or emulator was available |

The live Neo4j tests are skipped unless credentials are provided:

```text
# pytest (the password is read from the environment, never stored)
OLS_LIVE_NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io  OLS_LIVE_NEO4J_PASSWORD=…  pytest tests/test_live_neo4j.py

# browser journey (the backend process needs the password in the variable named by E2E_NEO4J_PASSWORD_VAR)
E2E_NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io  E2E_NEO4J_PASSWORD_VAR=NEO4J_PASSWORD  npm run e2e:neo4j
```

## Known limitations

* GraphDB, Fuseki and Cosmos DB deployment are implemented but unverified against live servers; the UI and
  API label them *Adapter not live-tested*. GraphDB's token authentication (`Authorization: GDB`) is
  sent as documented but has not been exercised against GraphDB.
* The graph data written to Neo4j or Cosmos DB is a *projection* of the accepted facts; ontology axioms and
  SHACL shapes are not stored in property-graph targets (the compatibility report says so), and Neo4j
  deployments add the marker label `OlsVertex` and `_ols_*` properties.
* A property-graph deployment replaces its build scope in several transactions; a failed deployment attempts
  to remove the partial scope, and re-deploying always starts from a clean scope.
* Cosmos DB explorer reads fetch the build's partition (up to the explorer limits) and filter client-side for
  search; very large builds are better explored in Neo4j or an RDF store.
