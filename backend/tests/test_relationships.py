from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import add_class, error_code


def test_create_relationship_between_classes(client: TestClient, ontology: dict[str, Any]) -> None:
    oid = ontology["id"]
    supplier = add_class(client, oid, "Supplier")
    product = add_class(client, oid, "Product")

    response = client.post(
        f"/api/ontologies/{oid}/object-properties",
        json={
            "label": "supplies",
            "description": "Supplier provides product",
            "domain_id": supplier["id"],
            "range_id": product["id"],
        },
    )
    assert response.status_code == 201
    rel = response.json()
    assert rel["local_name"] == "supplies"
    assert (rel["domain_id"], rel["range_id"]) == (supplier["id"], product["id"])

    draft = client.get(f"/api/ontologies/{oid}/draft").json()
    assert draft["object_properties"] == [rel]
    assert draft["ontology"]["stats"]["object_property_count"] == 1


def test_relationship_requires_existing_domain_and_range(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    oid = ontology["id"]
    supplier = add_class(client, oid, "Supplier")
    response = client.post(
        f"/api/ontologies/{oid}/object-properties",
        json={"label": "supplies", "domain_id": supplier["id"], "range_id": "cls-missing"},
    )
    assert response.status_code == 422
    assert error_code(response) == "UNKNOWN_CLASS_REFERENCE"
    assert response.json()["error"]["details"]["field"] == "range_id"


def test_self_referencing_relationship_is_allowed(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    product = add_class(client, ontology["id"], "Product")
    response = client.post(
        f"/api/ontologies/{ontology['id']}/object-properties",
        json={"label": "has component", "domain_id": product["id"], "range_id": product["id"]},
    )
    assert response.status_code == 201
    assert response.json()["local_name"] == "hasComponent"


def test_update_and_delete_relationship(client: TestClient, ontology: dict[str, Any]) -> None:
    oid = ontology["id"]
    shipment = add_class(client, oid, "Shipment")
    facility = add_class(client, oid, "Facility")
    carrier = add_class(client, oid, "Carrier")
    rel = client.post(
        f"/api/ontologies/{oid}/object-properties",
        json={"label": "ships to", "domain_id": shipment["id"], "range_id": facility["id"]},
    ).json()

    updated = client.patch(
        f"/api/ontologies/{oid}/object-properties/{rel['id']}",
        json={"label": "carried by", "local_name": "carriedBy", "range_id": carrier["id"]},
    )
    assert updated.status_code == 200
    assert (updated.json()["label"], updated.json()["range_id"]) == ("carried by", carrier["id"])

    invalid = client.patch(
        f"/api/ontologies/{oid}/object-properties/{rel['id']}", json={"domain_id": "missing"}
    )
    assert invalid.status_code == 422

    assert client.delete(f"/api/ontologies/{oid}/object-properties/{rel['id']}").status_code == 204
    missing = client.get(f"/api/ontologies/{oid}/object-properties/{rel['id']}")
    assert missing.status_code == 404
    assert error_code(missing) == "OBJECT_PROPERTY_NOT_FOUND"


def test_relationship_local_name_cannot_collide_with_class(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    oid = ontology["id"]
    a = add_class(client, oid, "Order")
    response = client.post(
        f"/api/ontologies/{oid}/object-properties",
        json={"label": "x", "local_name": "Order", "domain_id": a["id"], "range_id": a["id"]},
    )
    assert response.status_code == 409
    assert error_code(response) == "LOCAL_NAME_TAKEN"
