from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import ONTOLOGY_PAYLOAD, add_class, error_code


def _revision(client: TestClient, ontology_id: str) -> int:
    return client.get(f"/api/ontologies/{ontology_id}").json()["draft_revision"]


# ------------------------------------------------------------------------------ ontology


def test_ontology_create_update_delete(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "P"}).json()
    created = client.post(f"/api/projects/{project['id']}/ontologies", json=ONTOLOGY_PAYLOAD)
    assert created.status_code == 201
    ontology = created.json()

    duplicate = client.post(f"/api/projects/{project['id']}/ontologies", json=ONTOLOGY_PAYLOAD)
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "ONTOLOGY_NAME_TAKEN"

    updated = client.patch(f"/api/ontologies/{ontology['id']}", json={"description": "New"})
    assert updated.json()["description"] == "New"
    assert updated.json()["draft_revision"] == 2

    no_op = client.patch(f"/api/ontologies/{ontology['id']}", json={"description": "New"})
    assert no_op.json()["draft_revision"] == 2, "no-op updates must not create revisions"

    assert client.delete(f"/api/ontologies/{ontology['id']}").status_code == 204
    assert client.get(f"/api/ontologies/{ontology['id']}").status_code == 404


# ------------------------------------------------------------------------------ classes


def test_create_class_derives_identifiers(client: TestClient, ontology: dict[str, Any]) -> None:
    cls = add_class(client, ontology["id"], "purchase order", aliases=["PO", " po ", ""])
    assert cls["local_name"] == "PurchaseOrder"
    assert cls["id"].startswith("cls_")
    assert cls["aliases"] == ["PO"], "aliases are trimmed and de-duplicated case-insensitively"
    assert _revision(client, ontology["id"]) == 2

    fetched = client.get(f"/api/ontologies/{ontology['id']}/classes/{cls['id']}").json()
    assert fetched == cls


def test_update_class(client: TestClient, ontology: dict[str, Any]) -> None:
    cls = add_class(client, ontology["id"], "Vendor")
    response = client.patch(
        f"/api/ontologies/{ontology['id']}/classes/{cls['id']}",
        json={"label": "Supplier", "local_name": "Supplier", "description": "Provides goods"},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["label"], body["local_name"], body["description"]) == (
        "Supplier",
        "Supplier",
        "Provides goods",
    )


def test_class_local_names_must_be_unique(client: TestClient, ontology: dict[str, Any]) -> None:
    add_class(client, ontology["id"], "Supplier")
    response = client.post(f"/api/ontologies/{ontology['id']}/classes", json={"label": "Supplier"})
    assert response.status_code == 409
    assert error_code(response) == "LOCAL_NAME_TAKEN"


def test_explicit_element_ids_must_be_unique(client: TestClient, ontology: dict[str, Any]) -> None:
    add_class(client, ontology["id"], "A", id="cls-a")
    response = client.post(
        f"/api/ontologies/{ontology['id']}/classes", json={"label": "B", "id": "cls-a"}
    )
    assert response.status_code == 409
    assert error_code(response) == "ELEMENT_ID_TAKEN"


def test_class_hierarchy(client: TestClient, ontology: dict[str, Any]) -> None:
    oid = ontology["id"]
    org = add_class(client, oid, "Organization")
    supplier = add_class(client, oid, "Supplier", parent_ids=[org["id"]])
    assert supplier["parent_ids"] == [org["id"]]

    unknown = client.post(
        f"/api/ontologies/{oid}/classes", json={"label": "X", "parent_ids": ["cls-missing"]}
    )
    assert unknown.status_code == 422
    assert error_code(unknown) == "UNKNOWN_CLASS_REFERENCE"

    cycle = client.patch(
        f"/api/ontologies/{oid}/classes/{org['id']}", json={"parent_ids": [supplier["id"]]}
    )
    assert cycle.status_code == 422
    assert error_code(cycle) == "CLASS_HIERARCHY_CYCLE"

    self_parent = client.patch(
        f"/api/ontologies/{oid}/classes/{org['id']}", json={"parent_ids": [org["id"]]}
    )
    assert error_code(self_parent) == "CLASS_HIERARCHY_CYCLE"


def test_delete_class_requires_cascade_when_referenced(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    oid = ontology["id"]
    org = add_class(client, oid, "Organization", position={"x": 10, "y": 20})
    supplier = add_class(client, oid, "Supplier", parent_ids=[org["id"]])
    facility = add_class(client, oid, "Facility")
    rel = client.post(
        f"/api/ontologies/{oid}/object-properties",
        json={"label": "operates", "domain_id": org["id"], "range_id": facility["id"]},
    ).json()
    attr = client.post(
        f"/api/ontologies/{oid}/datatype-properties",
        json={"label": "legal name", "domain_id": org["id"]},
    ).json()

    blocked = client.delete(f"/api/ontologies/{oid}/classes/{org['id']}")
    assert blocked.status_code == 409
    assert error_code(blocked) == "CLASS_HAS_DEPENDENTS"
    assert blocked.json()["error"]["details"]["child_class_ids"] == [supplier["id"]]

    result = client.delete(f"/api/ontologies/{oid}/classes/{org['id']}?cascade=true").json()
    assert result["removed_object_property_ids"] == [rel["id"]]
    assert result["removed_datatype_property_ids"] == [attr["id"]]
    assert result["detached_child_class_ids"] == [supplier["id"]]

    draft = client.get(f"/api/ontologies/{oid}/draft").json()
    assert [c["id"] for c in draft["classes"]] == [supplier["id"], facility["id"]]
    assert draft["classes"][0]["parent_ids"] == []
    assert draft["object_properties"] == [] and draft["datatype_properties"] == []
    assert org["id"] not in draft["layout"]["positions"]


def test_unreferenced_class_can_be_deleted(client: TestClient, ontology: dict[str, Any]) -> None:
    cls = add_class(client, ontology["id"], "Temp")
    response = client.delete(f"/api/ontologies/{ontology['id']}/classes/{cls['id']}")
    assert response.status_code == 200
    assert client.get(f"/api/ontologies/{ontology['id']}/classes/{cls['id']}").status_code == 404


# ------------------------------------------------------------------------------ datatype properties


def test_datatype_property_crud(client: TestClient, ontology: dict[str, Any]) -> None:
    oid = ontology["id"]
    product = add_class(client, oid, "Product")
    created = client.post(
        f"/api/ontologies/{oid}/datatype-properties",
        json={"label": "unit cost", "domain_id": product["id"], "datatype": "decimal", "required": True},
    )
    assert created.status_code == 201
    prop = created.json()
    assert (prop["local_name"], prop["datatype"], prop["required"]) == ("unitCost", "decimal", True)

    updated = client.patch(
        f"/api/ontologies/{oid}/datatype-properties/{prop['id']}",
        json={"datatype": "integer", "multi_valued": True},
    ).json()
    assert (updated["datatype"], updated["multi_valued"]) == ("integer", True)

    bad_type = client.patch(
        f"/api/ontologies/{oid}/datatype-properties/{prop['id']}", json={"datatype": "money"}
    )
    assert bad_type.status_code == 422

    assert client.delete(f"/api/ontologies/{oid}/datatype-properties/{prop['id']}").status_code == 204
    assert client.get(f"/api/ontologies/{oid}/datatype-properties").json() == []


def test_unknown_ontology_returns_404(client: TestClient) -> None:
    response = client.post("/api/ontologies/nope/classes", json={"label": "X"})
    assert response.status_code == 404
    assert error_code(response) == "ONTOLOGY_NOT_FOUND"
