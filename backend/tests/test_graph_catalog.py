"""Provider-aware graph database registry: catalogue, per-provider forms, validation and registry management."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.graph.targets.catalog import (
    KINDS,
    REGISTRATION_ORDER,
    normalize_config,
    sparql_endpoints,
)
from tests.conftest import error_code

ADMIN = "Registry Admin"
URL = "/api/settings/graph-connections"


def _post(client: TestClient, name: str, kind: str, config: dict[str, Any], secret_env: str | None = None, **extra: Any) -> Any:
    body = {"name": name, "kind": kind, "config": config, "secret_env": secret_env, **extra}
    return client.post(URL, params={"actor": ADMIN}, json=body)


NEO4J = {"uri": "neo4j+s://abc123.databases.neo4j.io", "database": "neo4j", "username": "neo4j"}
COSMOS = {
    "endpoint": "my-account", "database": "graphdb", "graph": "knowledge", "partition_key_path": "/pk", "port": 443,
}
GRAPHDB = {"server_url": "http://localhost:7200", "repository_id": "knowledge"}
FUSEKI = {"query_url": "http://localhost:3030/ds/query", "update_url": "http://localhost:3030/ds/update"}


# ---------------------------------------------------------------------------------- catalogue


def test_every_registrable_provider_defines_its_form_and_model() -> None:
    assert REGISTRATION_ORDER == ("cosmos-gremlin", "neo4j", "graphdb", "fuseki", "sparql-http", "local-sql")
    models = {k: KINDS[k].model for k in REGISTRATION_ORDER}
    assert models == {
        "cosmos-gremlin": "property-graph", "neo4j": "property-graph", "graphdb": "rdf", "fuseki": "rdf",
        "sparql-http": "rdf", "local-sql": "property-graph",
    }
    keys = {k: [f.key for f in KINDS[k].fields] for k in REGISTRATION_ORDER}
    assert keys["cosmos-gremlin"] == ["endpoint", "port", "database", "graph", "partition_key_path", "secret_env", "timeout_seconds"]
    assert keys["neo4j"] == ["uri", "database", "username", "secret_env", "timeout_seconds"]
    assert keys["graphdb"][:5] == ["server_url", "repository_id", "query_url", "update_url", "access_mode"]
    assert keys["fuseki"][:2] == ["query_url", "update_url"] and keys["local-sql"] == []
    for kind in KINDS.values():
        for spec in kind.fields:
            if spec.visible_when:
                controller = spec.visible_when[0]
                assert controller in [f.key for f in kind.fields], "a conditional field refers to a field of its own form"


def test_catalogue_endpoint_exposes_dynamic_field_metadata(client: TestClient) -> None:
    kinds = {k["id"]: k for k in client.get("/api/settings/graph-kinds").json()}
    cosmos = {f["key"]: f for f in kinds["cosmos-gremlin"]["fields"]}
    assert cosmos["port"]["type"] == "integer" and cosmos["port"]["default"] == "443"
    assert cosmos["partition_key_path"]["required"] and cosmos["secret_env"]["secret"]
    graphdb = {f["key"]: f for f in kinds["graphdb"]["fields"]}
    assert graphdb["auth_type"]["type"] == "select"
    assert {o["value"] for o in graphdb["auth_type"]["options"]} == {"none", "basic", "bearer", "gdb-token"}
    assert graphdb["username"]["visible_when"] == {"field": "auth_type", "values": ["basic"]}
    assert graphdb["secret_env"]["visible_when"]["values"] == ["basic", "bearer", "gdb-token"]
    assert kinds["neo4j"]["protocol"].startswith("Bolt") and kinds["cosmos-gremlin"]["protocol"].startswith("Gremlin")


# ---------------------------------------------------------------------------------- validation


def test_graphdb_endpoints_are_derived_and_overridable() -> None:
    config, secret = normalize_config("graphdb", dict(GRAPHDB), None, allow_private=True)
    assert secret is None and config["access_mode"] == "read-write" and config["auth_type"] == "none"
    assert sparql_endpoints("graphdb", config) == (
        "http://localhost:7200/repositories/knowledge", "http://localhost:7200/repositories/knowledge/statements",
    )
    read_only, _ = normalize_config("graphdb", {**GRAPHDB, "access_mode": "read-only"}, None, allow_private=True)
    assert sparql_endpoints("graphdb", read_only)[1] is None
    override, _ = normalize_config(
        "graphdb", {**GRAPHDB, "query_url": "http://localhost:7200/q", "update_url": "http://localhost:7200/u"}, None,
        allow_private=True,
    )
    assert sparql_endpoints("graphdb", override) == ("http://localhost:7200/q", "http://localhost:7200/u")
    azure, _ = normalize_config(
        "graphdb", {"server_url": "https://graphdb.contoso.azure.example.com/", "repository_id": "kg"}, None, allow_private=True
    )
    assert azure["server_url"] == "https://graphdb.contoso.azure.example.com", "Azure-hosted GraphDB is just a server URL"


def test_authentication_fields_depend_on_the_selected_type() -> None:
    with pytest.raises(Exception, match="User name"):
        normalize_config("fuseki", {**FUSEKI, "auth_type": "basic"}, "FUSEKI_PW", allow_private=True)
    with pytest.raises(Exception, match="Credential"):
        normalize_config("fuseki", {**FUSEKI, "auth_type": "bearer"}, None, allow_private=True)
    config, secret = normalize_config(
        "fuseki", {**FUSEKI, "auth_type": "none", "username": "ignored"}, "UNUSED_VAR", allow_private=True
    )
    assert "username" not in config and secret is None, "hidden fields and credentials are dropped"
    config, secret = normalize_config("graphdb", {**GRAPHDB, "auth_type": "gdb-token"}, "GDB_TOKEN", allow_private=True)
    assert config["auth_type"] == "gdb-token" and secret == "GDB_TOKEN"
    with pytest.raises(Exception, match="Authentication"):
        normalize_config("fuseki", {**FUSEKI, "auth_type": "gdb-token"}, "X", allow_private=True)


def test_legacy_generic_sparql_configuration_keeps_working() -> None:
    legacy, secret = normalize_config(
        "sparql-http", {"query_url": "http://localhost:3030/q", "username": "reader"}, "OLS_SPARQL_PASSWORD", allow_private=True
    )
    assert legacy["auth_type"] == "basic" and legacy["username"] == "reader" and secret == "OLS_SPARQL_PASSWORD"
    query_only, _ = normalize_config("sparql-http", {"query_url": "http://localhost:3030/q"}, None, allow_private=True)
    assert sparql_endpoints("sparql-http", query_only) == ("http://localhost:3030/q", None)


def test_cosmos_endpoint_forms_ports_and_partition_keys() -> None:
    for given, stored in [
        ("my-account", "my-account.gremlin.cosmos.azure.com"),
        ("My-Account.gremlin.cosmos.azure.com", "my-account.gremlin.cosmos.azure.com"),
        ("wss://my-account.gremlin.cosmos.azure.com:443/", "my-account.gremlin.cosmos.azure.com"),
        ("acct.gremlin.cosmosdb.azure.com", "acct.gremlin.cosmosdb.azure.com"),
        ("ws://localhost:8901/", "ws://localhost"),
    ]:
        config, secret = normalize_config(
            "cosmos-gremlin", {**COSMOS, "endpoint": given}, "COSMOS_KEY", allow_private=True
        )
        assert config["endpoint"] == stored and config["port"] == "443" and config["timeout_seconds"] == "30"
        assert secret == "COSMOS_KEY"
    for bad, reason in [
        ({"endpoint": "evil.example.com"}, "gremlin.cosmos.azure.com"),
        ({"endpoint": "ws://my-account.gremlin.cosmos.azure.com"}, "plain ws://"),
        ({"endpoint": "https://my-account.gremlin.cosmos.azure.com"}, "ws://"),
        ({"endpoint": "169.254.169.254"}, "not allowed"),
        ({"port": 70000}, "between 1 and 65535"),
        ({"partition_key_path": "pk"}, "partition-key path"),
        ({"partition_key_path": "/a/b"}, "partition-key path"),
        ({"graph": "a/b"}, "Graph / container"),
        ({"timeout_seconds": 1}, "between 5 and 120"),
    ]:
        with pytest.raises(Exception, match=reason):
            normalize_config("cosmos-gremlin", {**COSMOS, **bad}, "COSMOS_KEY", allow_private=True)
    with pytest.raises(Exception, match="Account key"):
        normalize_config("cosmos-gremlin", dict(COSMOS), None, allow_private=True)


def test_neo4j_requires_its_fields_and_safe_uris() -> None:
    config, secret = normalize_config("neo4j", dict(NEO4J), "NEO4J_PASSWORD", allow_private=True)
    assert config["timeout_seconds"] == "15" and secret == "NEO4J_PASSWORD"
    for bad, reason in [
        ({"uri": "bolt://db.example.com"}, "encrypted"),
        ({"uri": ""}, "Bolt URI"),
        ({"database": "a b"}, "Database name"),
    ]:
        with pytest.raises(Exception, match=reason):
            normalize_config("neo4j", {**NEO4J, **bad}, "NEO4J_PASSWORD", allow_private=True)
    with pytest.raises(Exception, match="Password"):
        normalize_config("neo4j", dict(NEO4J), None, allow_private=True)
    local, _ = normalize_config("neo4j", {**NEO4J, "uri": "bolt://localhost:7687"}, "NEO4J_PASSWORD", allow_private=True)
    assert local["uri"] == "bolt://localhost:7687"
    with pytest.raises(Exception, match="private and loopback"):
        normalize_config("neo4j", {**NEO4J, "uri": "bolt://localhost:7687"}, "P", allow_private=False)


# ---------------------------------------------------------------------------------- API registration


def test_each_provider_registers_persists_and_reports_capabilities(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_PASSWORD", "never-return-this-value")
    cases = [
        ("Aura", "neo4j", NEO4J, "NEO4J_PASSWORD", "property-graph"),
        ("Cosmos", "cosmos-gremlin", COSMOS, "COSMOS_KEY", "property-graph"),
        ("GraphDB", "graphdb", GRAPHDB, None, "rdf"),
        ("Fuseki", "fuseki", FUSEKI, None, "rdf"),
        ("Generic", "sparql-http", {"query_url": "http://localhost:3030/ds/query"}, None, "rdf"),
        ("Local copy", "local-sql", {}, None, "property-graph"),
    ]
    created = {}
    for name, kind, config, secret, model in cases:
        response = _post(client, name, kind, config, secret)
        assert response.status_code == 201, response.text
        row = response.json()
        created[name] = row
        assert row["provider"] == row["kind"] == kind and row["model"] == model
        assert row["status"] == "not_tested" and row["last_test"] is None and row["enabled"] is True
        assert row["capabilities"]["registered"] and not row["capabilities"]["connected"]
        assert row["capabilities"]["connection_supported"] and row["capabilities"]["deployment_supported"]
        assert row["capabilities"]["deployment_verified"] is False and row["deployment_count"] == 0
    assert created["Aura"]["secret_present"] is True and created["Cosmos"]["secret_present"] is False
    assert created["Aura"]["capabilities"]["live_tested"] is True and created["Cosmos"]["capabilities"]["live_tested"] is False
    assert created["Aura"]["capabilities"]["deployment_ready"] is False, "an untested external database is not deployment-ready"
    assert created["Local copy"]["capabilities"]["deployment_ready"] is True, "the local store needs no connection test"
    assert created["GraphDB"]["effective_endpoints"]["update"].endswith("/repositories/knowledge/statements")
    assert created["Generic"]["capabilities"]["write_configured"] is False and created["Fuseki"]["capabilities"]["write_configured"]

    assert _post(client, "Aura", "neo4j", NEO4J, "NEO4J_PASSWORD").status_code == 409, "names are unique"
    again = _post(client, "Aura 2", "neo4j", {**NEO4J, "database": "other"}, "NEO4J_PASSWORD")
    assert again.status_code == 201, "several registrations of one provider are allowed"

    listing = client.get(URL).text
    assert "never-return-this-value" not in listing, "credential values are never returned"
    assert json.loads(listing)[0]["id"] == "local-sql"
    persisted = {c["name"]: c for c in client.get(URL).json() if not c["builtin"]}
    assert set(persisted) == {*created, "Aura 2"}


def test_edit_resets_the_test_only_when_the_connection_changes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    row = _post(client, "Aura", "neo4j", NEO4J, "NEO4J_PASSWORD").json()
    body = {"name": "Aura", "kind": "neo4j", "config": NEO4J, "secret_env": "NEO4J_PASSWORD"}
    put = lambda **changes: client.put(f"{URL}/{row['id']}", params={"actor": ADMIN}, json={**body, **changes})
    assert put(description="documented").json()["description"] == "documented"
    changed = put(config={**NEO4J, "database": "other"})
    assert changed.status_code == 200 and changed.json()["config"]["database"] == "other"
    assert put(kind="graphdb").status_code == 422 and error_code(put(kind="graphdb")) == "GRAPH_KIND_IMMUTABLE"
    assert put(config={**NEO4J, "uri": "bolt://db.example.com"}).status_code == 422


def test_secrets_belong_in_environment_variables_not_in_registrations(client: TestClient) -> None:
    pasted = "FAKE-pasted-graph-credential-that-must-never-be-echoed"
    response = _post(client, "Oops", "neo4j", NEO4J, pasted)
    assert response.status_code == 422 and pasted not in response.text
    response = _post(client, "Oops", "neo4j", {**NEO4J, "password": pasted}, "NEO4J_PASSWORD")
    assert response.status_code == 422 and error_code(response) == "GRAPH_CONFIG_INVALID"
    assert pasted not in response.text


def test_provider_alias_is_accepted_on_input(client: TestClient) -> None:
    created = client.post(URL, json={"name": "Alias", "provider": "fuseki", "config": FUSEKI})
    assert created.status_code == 201 and created.json()["kind"] == "fuseki"
    conflicting = client.post(URL, json={"name": "Alias 2", "provider": "fuseki", "kind": "neo4j", "config": FUSEKI})
    assert conflicting.status_code == 422


def test_enable_disable_default_and_safe_delete(client: TestClient) -> None:
    graphdb = _post(client, "GraphDB", "graphdb", GRAPHDB).json()
    read_only = _post(client, "Read only", "sparql-http", {"query_url": "http://localhost:3030/q"}).json()
    project = client.post("/api/projects", json={"name": "Uses it", "default_graph_connection_id": graphdb["id"]}).json()
    assert project["default_graph_connection_id"] == graphdb["id"]

    in_use = client.post(f"{URL}/{graphdb['id']}/activation", json={"enabled": False})
    assert in_use.status_code == 409 and error_code(in_use) == "CONFIG_IN_USE"
    assert client.delete(f"{URL}/{graphdb['id']}").status_code == 409

    default = client.post(f"{URL}/{graphdb['id']}/default", params={"actor": ADMIN})
    assert default.status_code == 200 and default.json()["is_default"] is True
    refused = client.post(f"{URL}/{read_only['id']}/default")
    assert refused.status_code == 422 and error_code(refused) == "GRAPH_DEFAULT_NOT_WRITABLE"
    assert client.post(f"{URL}/oxigraph-embedded/default").status_code == 422

    created = client.post("/api/projects", json={"name": "Gets the default"}).json()
    assert created["default_graph_connection_id"] == graphdb["id"], "new projects preselect the workspace default"
    explicit = client.post("/api/projects", json={"name": "Explicit local", "default_graph_connection_id": "local-sql"}).json()
    assert explicit["default_graph_connection_id"] == "local-sql"
    existing = client.get(f"/api/projects/{project['id']}").json()
    assert existing["default_graph_connection_id"] == graphdb["id"]

    flags = {c["id"]: c["is_default"] for c in client.get(URL).json()}
    assert flags[graphdb["id"]] is True and flags["local-sql"] is False
    assert client.post(f"{URL}/local-sql/default").json()["is_default"] is True
    assert {c["id"]: c["is_default"] for c in client.get(URL).json()}[graphdb["id"]] is False

    spare = _post(client, "Spare", "fuseki", FUSEKI).json()
    disabled = client.post(f"{URL}/{spare['id']}/activation", json={"enabled": False})
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert disabled.json()["capabilities"]["deployment_ready"] is False
    blocked = client.post("/api/projects", json={"name": "Disabled target", "default_graph_connection_id": spare["id"]})
    assert blocked.status_code == 409 and error_code(blocked) == "GRAPH_CONNECTION_DISABLED"
    assert client.post(f"{URL}/{spare['id']}/default").status_code == 422
    assert client.post(f"{URL}/{spare['id']}/activation", json={"enabled": True}).json()["enabled"] is True
    assert client.delete(f"{URL}/{spare['id']}").status_code == 204
    assert client.post(f"{URL}/local-sql/activation", json={"enabled": False}).status_code == 422
