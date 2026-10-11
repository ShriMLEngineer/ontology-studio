from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.ontology.domain import NodeShape
from app.modules.semantics.graphs import RdfFormat
from app.modules.shacl.engine import ShapesCheck


class GeneratedConstraintRead(BaseModel):
    iri: str
    property_id: str
    property_label: str
    kind: Literal["attribute", "relationship"]
    datatype: str | None = None
    min_count: int | None = None
    max_count: int | None = None
    class_id: str | None = None


class GeneratedShapeRead(BaseModel):
    iri: str
    target_class_id: str
    label: str
    constraints: list[GeneratedConstraintRead]


class SignatureShapeRead(BaseModel):
    iri: str
    property_id: str
    side: Literal["domain", "range"]
    class_id: str
    label: str


class PreservedShapeRead(BaseModel):
    axiom_id: str
    kind: str
    summary: str
    ntriples: str
    anchor_ids: list[str]
    orphaned: bool


class ShapesOverview(BaseModel):
    ontology_id: str
    draft_revision: int
    authored: list[NodeShape]
    generated: list[GeneratedShapeRead]
    signatures: list[SignatureShapeRead]
    preserved: list[PreservedShapeRead]
    check: ShapesCheck
    triple_count: int


class SampleValidationRequest(BaseModel):
    data: str = Field(min_length=1, max_length=2_000_000, description="RDF instance data to validate")
    rdf_format: RdfFormat = "turtle"
    include_signature_shapes: bool = Field(
        default=False, description="Also enforce generated domain/range signature shapes (sh:targetSubjectsOf)"
    )


class ShaclValidationResponse(BaseModel):
    conforms: bool
    data_triples: int
    shapes_used: int
    duration_ms: int
    by_severity: dict[str, int]
    results: list[dict[str, Any]]


class ShapesImportResponse(BaseModel):
    preserved: list[PreservedShapeRead]
    triples: int
