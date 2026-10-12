"""Phase 4 Settings: registered LLM configurations, graph connections, project defaults and selection.

Connection tests are real HTTP calls; they run against small in-process harness servers (an
OpenAI-compatible /models endpoint and a SPARQL 1.1 query endpoint), never against mocks inside the
application.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from tests.conftest import error_code
from tests.kg_helpers import SME, run_build, setup_kg

ADMIN = "Ops Admin"


class _Harness(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # silence test output
        pass

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/models"):
            self._json(200, {"data": [{"id": "harness-model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode())
        if self.path.endswith("/sparql") and form.get("query", [""])[0].startswith("ASK"):
            self._json(200, {"head": {}, "boolean": False})
        else:
            self._json(404, {"error": "not found"})


@pytest.fixture
def harness() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Harness)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _llm(client: TestClient, base_url: str, **extra: Any) -> Any:
    body = {"name": "Harness model", "base_url": f"{base_url}/v1", "model": "harness-model", **extra}
    return client.post("/api/settings/llm-configurations", params={"actor": ADMIN}, json=body)


def test_llm_configurations_are_registered_tested_and_protected(client: TestClient, harness: str, monkeypatch: Any) -> None:
    listing = client.get("/api/settings/llm-configurations").json()
    assert listing[0]["id"] == "env-default" and listing[0]["builtin"] and listing[0]["configured"] is False

    created = _llm(client, harness, api_key_env="OLS_TEST_LLM_KEY")
    assert created.status_code == 201, created.text
    config = created.json()
    assert config["api_key_present"] is False and "api_key" not in json.dumps(config).replace("api_key_env", "").replace(
        "api_key_present", ""
    ), "secrets are referenced by variable name only"
    assert _llm(client, harness).status_code == 409

    missing_key = client.post(f"/api/settings/llm-configurations/{config['id']}/test").json()
    assert missing_key["last_test"]["ok"] is False and "OLS_TEST_LLM_KEY" in missing_key["last_test"]["message"]
    monkeypatch.setenv("OLS_TEST_LLM_KEY", "secret-value")
    tested = client.post(f"/api/settings/llm-configurations/{config['id']}/test").json()
    assert tested["last_test"]["ok"] is True and tested["last_test"]["details"]["model_listed"] is True
    assert "secret-value" not in json.dumps(tested)

    renamed = client.put(
        f"/api/settings/llm-configurations/{config['id']}",
        params={"actor": ADMIN},
        json={"name": "Harness model (renamed)", "base_url": f"{harness}/v1", "model": "other-model"},
    ).json()
    assert renamed["model"] == "other-model" and renamed["last_test"] is None, "edits invalidate the last test"
    unlisted = client.post(f"/api/settings/llm-configurations/{config['id']}/test").json()
    assert unlisted["last_test"]["ok"] is False and "not listed" in unlisted["last_test"]["message"]

    unreachable = _llm(client, "http://127.0.0.1:9", name="Nowhere").json()
    assert client.post(f"/api/settings/llm-configurations/{unreachable['id']}/test").json()["last_test"]["ok"] is False
    assert client.put("/api/settings/llm-configurations/env-default", json={"name": "x", "base_url": "http://x", "model": "m"}).status_code == 422
    invalid = client.post("/api/settings/llm-configurations", json={"name": "Bad", "base_url": "ftp://x", "model": "m"})
    assert invalid.status_code == 422


def test_pasted_secret_in_credential_field_is_rejected_without_being_echoed(client: TestClient) -> None:
    pasted = "FAKE-pasted-secret-value_that-must-never-be-echoed"
    for path, body in (
        ("/api/settings/llm-configurations", {"name": "Oops", "provider": "openai", "model": "m", "api_key_env": pasted}),
        ("/api/settings/graph-connections", {"name": "Oops", "kind": "sparql-http", "secret_env": pasted}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 422
        assert pasted not in response.text
        messages = " ".join(error["message"] for error in response.json()["error"]["details"]["errors"])
        assert "NAME of a server environment variable" in messages


def test_graph_connections_offer_only_available_adapters(client: TestClient, harness: str) -> None:
    kinds = {k["id"]: k for k in client.get("/api/settings/graph-kinds").json()}
    assert kinds["sparql-http"]["registrable"] and kinds["sparql-http"]["available"]
    assert not kinds["neo4j"]["available"] and "Neo4j server" in kinds["neo4j"]["unavailable_reason"]
    assert not kinds["cosmos-gremlin"]["available"]
    refused = client.post("/api/settings/graph-connections", json={"name": "Neo", "kind": "neo4j", "config": {}})
    assert refused.status_code == 422 and error_code(refused) == "GRAPH_KIND_NOT_AVAILABLE"
    incomplete = client.post("/api/settings/graph-connections", json={"name": "S", "kind": "sparql-http", "config": {}})
    assert incomplete.status_code == 422 and error_code(incomplete) == "GRAPH_CONFIG_INVALID"

    builtins = {c["id"]: c for c in client.get("/api/settings/graph-connections").json()}
    assert {"local-sql", "oxigraph-embedded"} <= set(builtins)
    assert client.post("/api/settings/graph-connections/local-sql/test").json()["last_test"]["ok"] is True
    oxigraph = client.post("/api/settings/graph-connections/oxigraph-embedded/test").json()
    assert oxigraph["last_test"]["ok"] is True and "Embedded Oxigraph store open" in oxigraph["last_test"]["message"]
    assert client.get("/api/settings/graph-connections/local-sql").json()["last_test"]["ok"] is True, "kept in app state"

    sparql = client.post(
        "/api/settings/graph-connections",
        params={"actor": ADMIN},
        json={"name": "Harness SPARQL", "kind": "sparql-http", "config": {"query_url": f"{harness}/sparql"}},
    ).json()
    tested = client.post(f"/api/settings/graph-connections/{sparql['id']}/test").json()
    assert tested["last_test"]["ok"] is True and "query-only" in tested["last_test"]["message"]
    down = client.post(
        "/api/settings/graph-connections",
        json={"name": "Down", "kind": "sparql-http", "config": {"query_url": "http://127.0.0.1:9/sparql"}},
    ).json()
    assert client.post(f"/api/settings/graph-connections/{down['id']}/test").json()["last_test"]["ok"] is False
    assert client.delete("/api/settings/graph-connections/local-sql").status_code == 422
    assert client.delete(f"/api/settings/graph-connections/{down['id']}").status_code == 204


def test_project_defaults_and_creation_use_registered_configurations(client: TestClient, harness: str) -> None:
    config = _llm(client, harness).json()
    graph = client.post(
        "/api/settings/graph-connections",
        json={"name": "Harness SPARQL", "kind": "sparql-http", "config": {"query_url": f"{harness}/sparql"}},
    ).json()
    project = client.post(
        "/api/projects",
        json={"name": "Configured", "default_llm_config_id": config["id"], "default_graph_connection_id": graph["id"]},
    )
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    assert project.json()["default_llm_config_id"] == config["id"]
    unknown = client.post("/api/projects", json={"name": "Broken", "default_llm_config_id": "nope"})
    assert unknown.status_code == 404

    defaults = client.get(f"/api/projects/{pid}/defaults").json()
    assert defaults["effective_llm"]["name"] == "Harness model" and defaults["effective_graph"]["kind"] == "sparql-http"
    status = client.get("/api/llm/status", params={"project_id": pid}).json()
    assert status["configured"] and status["config_name"] == "Harness model" and status["model"] == "harness-model"

    in_use = client.delete(f"/api/settings/llm-configurations/{config['id']}")
    assert in_use.status_code == 409 and error_code(in_use) == "CONFIG_IN_USE"
    bad_ns = client.put(f"/api/projects/{pid}/defaults", json={"data_namespace": "not-an-iri"})
    assert bad_ns.status_code == 422 and error_code(bad_ns) == "DATA_NAMESPACE_INVALID"
    reset = client.put(
        f"/api/projects/{pid}/defaults",
        params={"actor": ADMIN},
        json={"default_llm_config_id": "env-default", "default_graph_connection_id": "oxigraph-embedded",
              "data_namespace": "https://data.example.org/configured/"},
    ).json()
    assert reset["default_llm_config_id"] == "env-default" and reset["effective_graph"]["id"] == "oxigraph-embedded"
    assert client.delete(f"/api/settings/llm-configurations/{config['id']}").status_code == 204
    activity = client.get(f"/api/projects/{pid}/activity").json()
    assert any(e["event_type"] == "project.defaults_updated" for e in activity)


def test_kg_builds_record_the_selected_llm_and_graph_target(seeded_client: TestClient, harness: str) -> None:
    env = setup_kg(seeded_client, ["suppliers.csv"])
    client = env["client"]
    config = _llm(client, harness).json()
    client.put(f"/api/projects/{env['project']['id']}/defaults",
               json={"data_namespace": "https://data.example.org/sc/"})
    unknown = client.post(f"/api/projects/{env['project']['id']}/kg/builds", json={
        "ontology_version_id": env["version"]["id"], "source_document_ids": [env["documents"]["suppliers.csv"]["id"]],
        "requested_by": SME, "settings": {"llm_config_id": "missing"},
    })
    assert unknown.status_code == 404 and error_code(unknown) == "LLM_CONFIG_NOT_FOUND"

    build = run_build(env, llm_config_id=config["id"], graph_connection_id="oxigraph-embedded")
    snapshot_build = client.get(f"/api/kg/builds/{build['id']}").json()
    assert build["settings"]["llm_config_id"] == config["id"]
    assert snapshot_build["stats"]["shacl"]["data_namespace"] == "https://data.example.org/sc/"
    default_build = run_build(env)
    assert default_build["settings"]["llm_config_id"] is None


def test_discovery_runs_use_the_selected_configuration(studio: dict[str, Any], harness: str) -> None:
    client: TestClient = studio["client"]
    missing = client.post(
        f"/api/ontologies/{studio['ontology']['id']}/discovery-runs",
        json={"document_ids": [studio["document"]["id"]], "requested_by": SME, "llm_config_id": "missing"},
    )
    assert missing.status_code == 404
    config = _llm(client, harness).json()
    run = client.post(
        f"/api/ontologies/{studio['ontology']['id']}/discovery-runs",
        json={"document_ids": [studio["document"]["id"]], "requested_by": SME, "llm_config_id": config["id"]},
    )
    assert run.status_code == 202, run.text
    assert run.json()["model"] == "harness-model", "the run uses the registered configuration, not the default"
    default = client.post(
        f"/api/ontologies/{studio['ontology']['id']}/discovery-runs",
        json={"document_ids": [studio["document"]["id"]], "requested_by": SME},
    )
    assert default.status_code == 202 and default.json()["model"] == studio["provider"].model
