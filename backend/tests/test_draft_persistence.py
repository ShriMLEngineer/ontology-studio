from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import error_code


def _save_body(draft: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    ontology = draft["ontology"]
    body = {
        "base_revision": draft["draft_revision"],
        "metadata": {k: ontology[k] for k in ("name", "namespace", "prefix", "description")},
        "classes": draft["classes"],
        "object_properties": draft["object_properties"],
        "datatype_properties": draft["datatype_properties"],
        "layout": draft["layout"],
    }
    body.update(overrides)
    return body


def _seeded_draft(client: TestClient) -> dict[str, Any]:
    project = client.get("/api/projects").json()[0]
    ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
    return client.get(f"/api/ontologies/{ontology['id']}/draft").json()


def test_user_journey_changes_persist_across_restart(
    seeded_client: TestClient, restart_client: Callable[[], TestClient]
) -> None:
    """Add a class, edit a class, add a relationship, save, restart, verify."""
    draft = _seeded_draft(seeded_client)
    oid = draft["ontology"]["id"]
    start_revision = draft["draft_revision"]

    classes = [dict(c) for c in draft["classes"]]
    new_class = {
        "id": "cls-inventory-lot",
        "local_name": "InventoryLot",
        "label": "Inventory Lot",
        "description": "A quantity of a product held at a warehouse.",
        "aliases": ["Batch"],
        "parent_ids": [],
    }
    classes.append(new_class)
    supplier = next(c for c in classes if c["local_name"] == "Supplier")
    supplier["description"] = "An approved organization that provides products."
    supplier["aliases"] = ["Vendor", "Seller"]

    relationship = {
        "id": "op-held-at",
        "local_name": "heldAt",
        "label": "held at",
        "description": "The warehouse at which the lot is held.",
        "aliases": [],
        "domain_id": "cls-inventory-lot",
        "range_id": "cls-warehouse",
    }
    layout = {"positions": {**draft["layout"]["positions"], "cls-inventory-lot": {"x": 1200, "y": 700}}}

    response = seeded_client.put(
        f"/api/ontologies/{oid}/draft",
        json=_save_body(
            draft,
            classes=classes,
            object_properties=[*draft["object_properties"], relationship],
            layout=layout,
        ),
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision_incremented"] is True
    assert saved["changes"]["classes"] == {"added": 1, "updated": 1, "removed": 0}
    assert saved["changes"]["object_properties"] == {"added": 1, "updated": 0, "removed": 0}
    assert saved["draft"]["draft_revision"] == start_revision + 1

    with restart_client() as restarted:
        reloaded = restarted.get(f"/api/ontologies/{oid}/draft").json()

    assert reloaded["draft_revision"] == start_revision + 1
    by_id = {c["id"]: c for c in reloaded["classes"]}
    # Every element also carries the persisted IRI and OWL semantics (additive fields).
    assert {k: by_id["cls-inventory-lot"][k] for k in new_class} == new_class
    assert by_id["cls-inventory-lot"]["iri"] == "https://example.com/ontology/supply-chain#InventoryLot"
    assert by_id[supplier["id"]]["aliases"] == ["Vendor", "Seller"]
    assert by_id[supplier["id"]]["description"] == "An approved organization that provides products."
    saved_rel = next(p for p in reloaded["object_properties"] if p["id"] == relationship["id"])
    assert {k: saved_rel[k] for k in relationship} == relationship
    assert reloaded["layout"]["positions"]["cls-inventory-lot"] == {"x": 1200.0, "y": 700.0}
    assert [c["id"] for c in reloaded["classes"]][-1] == "cls-inventory-lot", "order is preserved"


def test_stale_base_revision_is_rejected(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    oid = draft["ontology"]["id"]
    seeded_client.post(f"/api/ontologies/{oid}/classes", json={"label": "Concurrent Edit"})

    response = seeded_client.put(f"/api/ontologies/{oid}/draft", json=_save_body(draft))
    assert response.status_code == 409
    assert error_code(response) == "DRAFT_REVISION_CONFLICT"
    details = response.json()["error"]["details"]
    assert details["current_revision"] == draft["draft_revision"] + 1


def test_noop_and_layout_only_saves_do_not_create_revisions(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    oid = draft["ontology"]["id"]

    no_op = seeded_client.put(f"/api/ontologies/{oid}/draft", json=_save_body(draft)).json()
    assert no_op["revision_incremented"] is False
    assert no_op["draft"]["draft_revision"] == draft["draft_revision"]

    moved = {"positions": {**draft["layout"]["positions"], "cls-product": {"x": -5, "y": 5}}}
    layout_only = seeded_client.put(
        f"/api/ontologies/{oid}/draft", json=_save_body(draft, layout=moved)
    ).json()
    assert layout_only["revision_incremented"] is False
    assert layout_only["changes"]["layout_changed"] is True
    assert layout_only["draft"]["layout"]["positions"]["cls-product"] == {"x": -5.0, "y": 5.0}


def test_save_removes_deleted_elements_and_prunes_layout(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    oid = draft["ontology"]["id"]
    classes = [c for c in draft["classes"] if c["id"] != "cls-customer"]
    layout = {"positions": {**draft["layout"]["positions"], "not-a-class": {"x": 1, "y": 1}}}

    saved = seeded_client.put(
        f"/api/ontologies/{oid}/draft", json=_save_body(draft, classes=classes, layout=layout)
    ).json()
    assert saved["changes"]["classes"]["removed"] == 1
    positions = saved["draft"]["layout"]["positions"]
    assert "cls-customer" not in positions and "not-a-class" not in positions


def test_duplicate_element_ids_are_rejected(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    clash = {**draft["object_properties"][0], "id": draft["classes"][0]["id"]}
    response = seeded_client.put(
        f"/api/ontologies/{draft['ontology']['id']}/draft",
        json=_save_body(draft, object_properties=[*draft["object_properties"], clash]),
    )
    assert response.status_code == 422
    assert error_code(response) == "DUPLICATE_ELEMENT_ID"


def test_invalid_payload_is_rejected_without_partial_writes(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    bad_class = {"id": "cls-bad", "local_name": "Bad", "label": "  "}
    response = seeded_client.put(
        f"/api/ontologies/{draft['ontology']['id']}/draft",
        json=_save_body(draft, classes=[*draft["classes"], bad_class]),
    )
    assert response.status_code == 422
    assert _seeded_draft(seeded_client) == draft


def test_metadata_is_saved_with_the_draft(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    metadata = {**{k: draft["ontology"][k] for k in ("name", "namespace", "prefix")}, "description": "Edited"}
    saved = seeded_client.put(
        f"/api/ontologies/{draft['ontology']['id']}/draft", json=_save_body(draft, metadata=metadata)
    ).json()
    assert saved["changes"]["metadata_changed"] is True
    assert saved["draft"]["ontology"]["description"] == "Edited"


def test_draft_save_is_recorded_in_activity(seeded_client: TestClient) -> None:
    draft = _seeded_draft(seeded_client)
    classes = [*draft["classes"], {"id": "cls-x", "local_name": "X", "label": "X"}]
    seeded_client.put(
        f"/api/ontologies/{draft['ontology']['id']}/draft", json=_save_body(draft, classes=classes)
    )
    project_id = draft["ontology"]["project_id"]
    latest = seeded_client.get(f"/api/projects/{project_id}/activity?limit=1").json()[0]
    assert latest["event_type"] == "ontology.draft_saved"
    assert "+1 class" in latest["summary"]
