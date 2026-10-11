"""Test doubles. Used only by automated tests - the application never fabricates LLM output."""

import json
from typing import Any

from pydantic import BaseModel

from app.modules.llm.provider import LLMUsage, StructuredResult


class ScriptedLLMProvider:
    """Returns pre-defined structured responses (or raises pre-defined errors) in order."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    @property
    def name(self) -> str:
        return "scripted-test-double"

    @property
    def model(self) -> str:
        return "scripted"

    def generate_structured(self, *, system: str, user: str, schema: type[BaseModel], schema_name: str) -> StructuredResult[Any]:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        item = self._responses.pop(0) if self._responses else {"findings": []}
        if isinstance(item, Exception):
            raise item
        return StructuredResult(
            value=schema.model_validate(item), raw_text=json.dumps(item), usage=LLMUsage(120, 60), attempts=1
        )


SOURCE_TEXT = """Supplier compliance and inventory handbook.

Every vendor must hold a valid certificate of insurance before a purchase order is issued.

Inventory lots are held at a warehouse and identified by a lot number. Each inventory lot contains a quantity of a single product.

The haulier (our carrier) is responsible for the shipment until it is delivered to the receiving facility.

Some carriers supply packaging products to the warehouse."""


def evidence(quote: str, chunk: str = "C1") -> list[dict[str, str]]:
    return [{"chunk_id": chunk, "quote": quote}]


DISCOVERY_FINDINGS: list[dict[str, Any]] = [
    {
        "action": "add", "element_kind": "class", "term": "inventory lots", "label": "Inventory Lot",
        "definition": "A quantity of a single product held at a warehouse under one lot number.",
        "rationale": "Inventory lots are a distinct tracked unit.", "confidence": 0.9,
        "evidence": evidence("Inventory lots are held at a warehouse and identified by a lot number."),
    },
    {
        "action": "add", "element_kind": "object_property", "term": "held at", "label": "held at",
        "definition": "The warehouse at which the inventory lot is held.", "domain": "Inventory Lot",
        "range": "cls-warehouse", "rationale": "Lots are held at warehouses.", "confidence": 0.85,
        "evidence": evidence("Inventory lots are held at a warehouse"),
    },
    {
        "action": "add", "element_kind": "datatype_property", "term": "lot number", "label": "lot number",
        "definition": "Identifier of an inventory lot.", "domain": "Inventory Lot", "datatype": "string",
        "rationale": "Lots are identified by a lot number.", "confidence": 0.8,
        "evidence": evidence("identified by a lot number"),
    },
    {
        "action": "add", "element_kind": "class", "term": "vendor", "label": "Vendor",
        "definition": "A company that sells to us.", "rationale": "Vendors are mentioned.", "confidence": 0.7,
        "evidence": evidence("Every vendor must hold a valid certificate of insurance"),
    },
    {
        "action": "alias", "element_kind": "class", "term": "haulier", "label": "Carrier", "target_id": "cls-carrier",
        "alias": "Haulier", "rationale": "Haulier is used for carrier.", "confidence": 0.75,
        "evidence": evidence("The haulier (our carrier) is responsible for the shipment"),
    },
    {
        "action": "modify", "element_kind": "class", "term": "shipment", "label": "Shipment", "target_id": "cls-shipment",
        "definition": "A consignment for which the carrier is responsible until it is delivered to the receiving facility.",
        "rationale": "The source clarifies carrier responsibility.", "confidence": 0.6,
        "evidence": evidence("is responsible for the shipment until it is delivered to the receiving facility"),
    },
    {
        "action": "add", "element_kind": "class", "term": "certificate of insurance", "label": "Certificate of Insurance",
        "definition": "Proof that a supplier holds valid insurance.", "rationale": "Required before ordering.",
        "confidence": 0.8, "evidence": evidence("hold a valid certificate of insurance"),
    },
    {
        "action": "add", "element_kind": "object_property", "term": "supply", "label": "supplies",
        "definition": "Provides products.", "domain": "Carrier", "range": "Product",
        "rationale": "Carriers supply packaging.", "confidence": 0.5,
        "evidence": evidence("Some carriers supply packaging products to the warehouse."),
    },
    {
        "action": "add", "element_kind": "class", "term": "customs broker", "label": "Customs Broker",
        "definition": "Clears imports.", "rationale": "Mentioned in source.", "confidence": 0.9,
        "evidence": evidence("Customs brokers clear all imported goods."),
    },
    {
        "action": "modify", "element_kind": "class", "term": "pallet", "label": "Pallet", "target_id": "cls-pallet",
        "definition": "A pallet.", "rationale": "Invented target.", "confidence": 0.4,
        "evidence": evidence("Each inventory lot contains a quantity of a single product."),
    },
]
