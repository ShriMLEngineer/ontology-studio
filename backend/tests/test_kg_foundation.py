"""Data sources, mappings, published-version enforcement and build configuration."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import error_code
from tests.kg_helpers import SME, publish, sample_bytes, save_suggested_mapping, setup_kg, upload


def _context(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    project = client.get("/api/projects").json()[0]
    ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
    return project, ontology


def test_only_published_versions_are_selectable(seeded_client: TestClient) -> None:
    project, ontology = _context(seeded_client)
    url = f"/api/projects/{project['id']}/kg/ontology-versions"
    assert seeded_client.get(url).json() == []

    version = publish(seeded_client, ontology["id"], "1.0.0")
    options = seeded_client.get(url).json()
    assert [(o["version"], o["is_latest"]) for o in options] == [("1.0.0", True)]

    document = upload(seeded_client, project["id"], "suppliers.csv")
    body = {"source_document_ids": [document["id"]], "requested_by": SME}
    draft = seeded_client.post(
        f"/api/projects/{project['id']}/kg/builds", json={**body, "ontology_version_id": ontology["id"]}
    )
    assert draft.status_code == 422
    assert error_code(draft) == "PUBLISHED_VERSION_REQUIRED"
    unknown = seeded_client.post(f"/api/projects/{project['id']}/kg/builds", json={**body, "ontology_version_id": "nope"})
    assert error_code(unknown) == "ONTOLOGY_VERSION_NOT_FOUND"
    ok = seeded_client.post(f"/api/projects/{project['id']}/kg/builds", json={**body, "ontology_version_id": version["id"]})
    assert ok.status_code == 201
    assert ok.json()["ontology_version"] == "1.0.0"


def test_structured_source_preview_profiles_columns(seeded_client: TestClient) -> None:
    project, _ = _context(seeded_client)
    document = upload(seeded_client, project["id"], "purchase_orders.csv")
    preview = seeded_client.get(f"/api/sources/{document['id']}/preview").json()
    assert preview["kind"] == "table"
    assert preview["total_rows"] == 3
    types = {c["name"]: c["inferred_datatype"] for c in preview["columns"]}
    assert types == {
        "po_number": "string",
        "order_date": "date",
        "supplier_id": "string",
        "product_id": "string",
        "quantity": "integer",
        "total_amount": "string",
    }
    assert preview["rows"][0] == {
        "row_number": 1,
        "values": {
            "po_number": "PO-7001",
            "order_date": "2026-07-14",
            "supplier_id": "S-001",
            "product_id": "P-100",
            "quantity": "20",
            "total_amount": "8400.00",
        },
    }
    pdf = upload(seeded_client, project["id"], "supplier-performance-review.pdf")
    text_preview = seeded_client.get(f"/api/sources/{pdf['id']}/preview").json()
    assert text_preview["kind"] == "text"
    assert text_preview["page_count"] == 2
    assert text_preview["chunk_count"] == 2, "PDF chunks never span pages"


def test_mapping_suggestion_follows_ontology_direction(seeded_client: TestClient) -> None:
    project, ontology = _context(seeded_client)
    version = publish(seeded_client, ontology["id"], "1.0.0")
    products = upload(seeded_client, project["id"], "products.csv")
    suggestion = seeded_client.get(
        f"/api/sources/{products['id']}/mapping-suggestion", params={"ontology_version_id": version["id"]}
    ).json()
    spec = suggestion["spec"]
    master, reference = spec["entities"]
    assert (master["class_id"], master["id_column"], master["label_column"], master["reference_only"]) == (
        "cls-product", "product_id", "product_name", False,
    )
    assert {a["column"]: a["property_id"] for a in master["attributes"]} == {
        "product_name": "dp-product-name", "sku": "dp-sku", "unit_cost": "dp-unit-cost",
    }
    assert (reference["class_id"], reference["reference_only"]) == ("cls-supplier", True)
    assert spec["relationships"] == [
        {"subject": reference["key"], "object": master["key"], "predicate_id": "op-supplies", "predicate_column": None}
    ]

    edges = upload(seeded_client, project["id"], "supply_relationships.csv")
    edge_spec = seeded_client.get(
        f"/api/sources/{edges['id']}/mapping-suggestion", params={"ontology_version_id": version["id"]}
    ).json()["spec"]
    assert [e["class_column"] for e in edge_spec["entities"]] == ["subject_type", "object_type"]
    assert edge_spec["relationships"][0]["predicate_column"] == "relationship"


def test_mapping_validation_rejects_unknown_columns_and_warns_on_direction(seeded_client: TestClient) -> None:
    project, ontology = _context(seeded_client)
    version = publish(seeded_client, ontology["id"], "1.0.0")
    products = upload(seeded_client, project["id"], "products.csv")
    url = f"/api/projects/{project['id']}/kg/mappings"
    spec = {
        "entities": [
            {"key": "p", "class_id": "cls-product", "id_column": "product_id"},
            {"key": "s", "class_id": "cls-supplier", "id_column": "supplier_id", "reference_only": True},
        ],
        "relationships": [{"subject": "p", "object": "s", "predicate_id": "op-supplies"}],
    }
    body = {"document_id": products["id"], "ontology_version_id": version["id"], "name": "reversed", "updated_by": SME}
    bad_column = {**spec, "entities": [{**spec["entities"][0], "id_column": "missing"}, spec["entities"][1]]}
    response = seeded_client.post(url, json={**body, "spec": bad_column})
    assert response.status_code == 422
    assert error_code(response) == "MAPPING_INVALID"
    assert response.json()["error"]["details"]["issues"][0]["code"] == "UNKNOWN_COLUMN"

    saved = seeded_client.post(url, json={**body, "spec": spec})
    assert saved.status_code == 201
    warning = saved.json()["issues"][0]
    assert warning["severity"] == "warning" and warning["code"] == "DOMAIN_RANGE_MISMATCH"
    assert "reversed" in warning["message"]

    duplicate = seeded_client.post(url, json={**body, "spec": spec})
    assert error_code(duplicate) == "MAPPING_NAME_TAKEN"
    invalid_spec = seeded_client.post(
        url, json={**body, "name": "x", "spec": {"entities": [{"key": "p", "id_column": "product_id"}]}}
    )
    assert invalid_spec.status_code == 422


def test_build_configuration_is_saved_and_checked_for_readiness(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client, ["suppliers.csv", "products.csv"])
    client, project = env["client"], env["project"]
    suppliers, products = env["documents"]["suppliers.csv"], env["documents"]["products.csv"]
    url = f"/api/projects/{project['id']}/kg/builds"
    created = client.post(
        url,
        json={
            "ontology_version_id": env["version"]["id"],
            "source_document_ids": [suppliers["id"], products["id"]],
            "mapping_ids": [env["mappings"]["suppliers.csv"]["id"]],
            "settings": {"max_chunks": 5, "extract_attributes": False},
            "requested_by": SME,
        },
    )
    assert created.status_code == 201
    build = created.json()
    assert build["status"] == "configured"
    assert build["settings"]["max_chunks"] == 5
    assert [s["status"] for s in build["stages"]] == ["pending"] * 10
    assert [s["key"] for s in build["stages"]][5:7] == ["structural_validation", "shacl_validation"]
    assert build["settings"]["validation_policy"] == "application-strict/1"
    assert build["readiness"]["ready"] is False
    assert [i["code"] for i in build["readiness"]["issues"]] == ["MAPPING_REQUIRED"]

    start = client.post(f"/api/kg/builds/{build['id']}/start", json={"requested_by": SME})
    assert start.status_code == 422 and error_code(start) == "KG_BUILD_NOT_READY"

    patched = client.patch(
        f"/api/kg/builds/{build['id']}",
        json={"mapping_ids": [env["mappings"]["suppliers.csv"]["id"], env["mappings"]["products.csv"]["id"]]},
    ).json()
    assert patched["readiness"]["ready"] is True
    reloaded = client.get(f"/api/kg/builds/{build['id']}").json()
    assert {s["mapping_name"] for s in reloaded["sources"]} == {"suppliers mapping", "products mapping"}
    assert client.get(url).json()[0]["id"] == build["id"]

    assert client.delete(f"/api/kg/builds/{build['id']}").status_code == 204
    assert client.get(f"/api/kg/builds/{build['id']}").status_code == 404


def test_document_sources_require_a_configured_llm(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client, ["supplier-performance-review.pdf"])
    client = env["client"]
    response = client.post(
        f"/api/projects/{env['project']['id']}/kg/builds",
        json={
            "ontology_version_id": env["version"]["id"],
            "source_document_ids": [env["documents"]["supplier-performance-review.pdf"]["id"]],
            "requested_by": SME,
            "start": True,
        },
    )
    assert response.status_code == 503
    assert error_code(response) == "LLM_NOT_CONFIGURED"


def test_mapping_in_use_cannot_be_deleted(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client, ["suppliers.csv"])
    client = env["client"]
    mapping = env["mappings"]["suppliers.csv"]
    client.post(
        f"/api/projects/{env['project']['id']}/kg/builds",
        json={
            "ontology_version_id": env["version"]["id"],
            "source_document_ids": [env["documents"]["suppliers.csv"]["id"]],
            "mapping_ids": [mapping["id"]],
            "requested_by": SME,
        },
    )
    response = client.delete(f"/api/kg/mappings/{mapping['id']}")
    assert error_code(response) == "MAPPING_IN_USE"


def test_saved_mappings_are_reusable_and_listed(seeded_client: TestClient) -> None:
    project, ontology = _context(seeded_client)
    version = publish(seeded_client, ontology["id"], "1.0.0")
    document = upload(seeded_client, project["id"], "suppliers.csv")
    mapping = save_suggested_mapping(seeded_client, project["id"], document, version["id"])
    listed = seeded_client.get(
        f"/api/projects/{project['id']}/kg/mappings", params={"document_id": document["id"]}
    ).json()
    assert [m["id"] for m in listed] == [mapping["id"]]
    assert listed[0]["ontology_version"] == "1.0.0"
    attributes = {a["column"] for a in listed[0]["spec"]["entities"][0]["attributes"]}
    assert attributes == {"legal_name", "tier", "risk_rating"}
    assert len(sample_bytes("suppliers.csv")) > 0
