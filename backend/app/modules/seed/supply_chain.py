"""Demonstration seed content for the Supply Chain domain.

This module contains *data only*. It is applied through the regular project/ontology services so
that seeded content obeys the same invariants as user-authored content.
"""

from typing import Any

PROJECT: dict[str, Any] = {
    "name": "Supply Chain",
    "business_domain": "Supply Chain",
    "description": (
        "Demonstration project: govern a Supply Chain ontology and use it to construct a "
        "knowledge graph from supplier, purchasing and logistics data."
    ),
}

ONTOLOGY: dict[str, Any] = {
    "name": "Supply Chain Core",
    "namespace": "https://example.com/ontology/supply-chain#",
    "prefix": "sc",
    "description": (
        "Core concepts for supplier management, manufacturing, inventory and logistics."
    ),
}

# (id, label, local_name, parent ids, description, aliases, (x, y))
_CLASSES: list[tuple[str, str, str, list[str], str, list[str], tuple[int, int]]] = [
    ("cls-organization", "Organization", "Organization", [],
     "A legal entity that participates in the supply chain, such as a company or business unit.",
     ["Company", "Business Partner"], (0, 0)),
    ("cls-supplier", "Supplier", "Supplier", ["cls-organization"],
     "An organization that provides products, materials or components to the enterprise.",
     ["Vendor"], (-340, 300)),
    ("cls-customer", "Customer", "Customer", ["cls-organization"],
     "An organization that purchases products from the enterprise.",
     ["Client", "Buyer"], (-20, 300)),
    ("cls-carrier", "Carrier", "Carrier", ["cls-organization"],
     "A logistics service provider that transports shipments between facilities.",
     ["Logistics Provider", "Freight Carrier"], (280, 300)),
    ("cls-facility", "Facility", "Facility", [],
     "A physical site where supply chain activities such as production or storage take place.",
     ["Site"], (700, 0)),
    ("cls-warehouse", "Warehouse", "Warehouse", ["cls-facility"],
     "A facility used to store inventory before it is distributed.",
     ["Distribution Center", "DC"], (560, 340)),
    ("cls-plant", "Manufacturing Plant", "ManufacturingPlant", ["cls-facility"],
     "A facility where products are manufactured or assembled.",
     ["Factory", "Plant"], (960, 340)),
    ("cls-location", "Location", "Location", [],
     "A geographic place identified by an address or coordinates.",
     ["Address", "Geography"], (1180, 0)),
    ("cls-product", "Product", "Product", [],
     "A good or material that is manufactured, purchased, stored or sold.",
     ["Item", "Material", "SKU"], (240, 560)),
    ("cls-purchase-order", "Purchase Order", "PurchaseOrder", [],
     "A commercial document issued to a supplier requesting products at agreed terms.",
     ["PO"], (-340, 700)),
    ("cls-shipment", "Shipment", "Shipment", [],
     "A consignment of products moved from one facility to another by a carrier.",
     ["Consignment", "Delivery"], (800, 700)),
]

# (id, label, local_name, domain, range, description)
_OBJECT_PROPERTIES: list[tuple[str, str, str, str, str, str]] = [
    ("op-operates", "operates", "operates", "cls-organization", "cls-facility",
     "The organization owns or operates the facility."),
    ("op-located-in", "located in", "locatedIn", "cls-facility", "cls-location",
     "The facility is physically located at the location."),
    ("op-supplies", "supplies", "supplies", "cls-supplier", "cls-product",
     "The supplier is an approved source of the product."),
    ("op-manufactures", "manufactures", "manufactures", "cls-plant", "cls-product",
     "The plant produces or assembles the product."),
    ("op-stores", "stores", "stores", "cls-warehouse", "cls-product",
     "The warehouse holds inventory of the product."),
    ("op-has-component", "has component", "hasComponent", "cls-product", "cls-product",
     "The product contains the other product as a component (bill of materials)."),
    ("op-issued-to", "issued to", "issuedTo", "cls-purchase-order", "cls-supplier",
     "The purchase order was issued to the supplier."),
    ("op-orders-product", "orders product", "ordersProduct", "cls-purchase-order", "cls-product",
     "The purchase order requests the product."),
    ("op-fulfills", "fulfills", "fulfills", "cls-shipment", "cls-purchase-order",
     "The shipment delivers goods requested by the purchase order."),
    ("op-ships-from", "ships from", "shipsFrom", "cls-shipment", "cls-facility",
     "The facility from which the shipment departs."),
    ("op-ships-to", "ships to", "shipsTo", "cls-shipment", "cls-facility",
     "The facility at which the shipment is delivered."),
    ("op-carried-by", "carried by", "carriedBy", "cls-shipment", "cls-carrier",
     "The carrier responsible for transporting the shipment."),
]

# (id, label, local_name, domain, datatype, required, description)
_DATATYPE_PROPERTIES: list[tuple[str, str, str, str, str, bool, str]] = [
    ("dp-legal-name", "legal name", "legalName", "cls-organization", "string", True,
     "Registered legal name of the organization."),
    ("dp-duns", "DUNS number", "dunsNumber", "cls-organization", "string", False,
     "Dun & Bradstreet unique business identifier."),
    ("dp-supplier-tier", "supplier tier", "supplierTier", "cls-supplier", "integer", False,
     "Tier of the supplier relative to the enterprise (1 = direct supplier)."),
    ("dp-risk-rating", "risk rating", "riskRating", "cls-supplier", "string", False,
     "Assessed supply risk category (e.g. low, medium, high)."),
    ("dp-facility-code", "facility code", "facilityCode", "cls-facility", "string", True,
     "Enterprise identifier of the facility."),
    ("dp-capacity", "capacity", "capacity", "cls-facility", "decimal", False,
     "Nominal throughput or storage capacity of the facility."),
    ("dp-country", "country", "country", "cls-location", "string", True,
     "ISO 3166 country code."),
    ("dp-city", "city", "city", "cls-location", "string", False, "City name."),
    ("dp-sku", "SKU", "sku", "cls-product", "string", True, "Stock keeping unit identifier."),
    ("dp-product-name", "product name", "productName", "cls-product", "string", True,
     "Commercial name of the product."),
    ("dp-unit-cost", "unit cost", "unitCost", "cls-product", "decimal", False,
     "Standard cost per unit in the reporting currency."),
    ("dp-order-number", "order number", "orderNumber", "cls-purchase-order", "string", True,
     "Purchase order document number."),
    ("dp-order-date", "order date", "orderDate", "cls-purchase-order", "date", True,
     "Date the purchase order was issued."),
    ("dp-total-amount", "total amount", "totalAmount", "cls-purchase-order", "decimal", False,
     "Total order value in the order currency."),
    ("dp-tracking-number", "tracking number", "trackingNumber", "cls-shipment", "string", True,
     "Carrier tracking reference."),
    ("dp-ship-date", "ship date", "shipDate", "cls-shipment", "date", False,
     "Date the shipment departed."),
    ("dp-expected-delivery", "expected delivery", "expectedDeliveryDate", "cls-shipment", "date",
     False, "Planned delivery date."),
]


def draft_content() -> dict[str, Any]:
    """Return seed content shaped like a draft-save request body (without base_revision)."""
    return {
        "metadata": ONTOLOGY,
        "classes": [
            {
                "id": cid,
                "label": label,
                "local_name": local_name,
                "parent_ids": parents,
                "description": description,
                "aliases": aliases,
            }
            for cid, label, local_name, parents, description, aliases, _ in _CLASSES
        ],
        "object_properties": [
            {
                "id": pid,
                "label": label,
                "local_name": local_name,
                "domain_id": domain,
                "range_id": range_,
                "description": description,
            }
            for pid, label, local_name, domain, range_, description in _OBJECT_PROPERTIES
        ],
        "datatype_properties": [
            {
                "id": pid,
                "label": label,
                "local_name": local_name,
                "domain_id": domain,
                "datatype": datatype,
                "required": required,
                "description": description,
            }
            for pid, label, local_name, domain, datatype, required, description in _DATATYPE_PROPERTIES
        ],
        "layout": {"positions": {cid: {"x": x, "y": y} for cid, *_, (x, y) in _CLASSES}},
    }
