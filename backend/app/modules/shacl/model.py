"""SHACL shapes for knowledge-graph data (Phase 4, milestone 4.2).

Three kinds of shapes make up the shapes graph of an ontology draft or published version:

* **generated** - derived from the ontology (``required`` -> ``sh:minCount 1``, single value ->
  ``sh:maxCount 1``, attribute datatype -> ``sh:datatype``, relationship range -> ``sh:class``),
  plus *signature* shapes (``sh:targetSubjectsOf`` / ``sh:targetObjectsOf`` + ``sh:class``) that
  only validation policies with SHACL-enforced signatures use;
* **authored** - node shapes created by SMEs in the Shapes tab (a structured subset of SHACL Core);
* **preserved** - imported SHACL kept verbatim (extension axioms with scope ``shapes``).

Shapes reference stable element ids; IRIs are only produced at serialisation. The models live in
the canonical ontology model (``ontology.domain``) because shapes are part of draft and snapshot.
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.ontology.domain import (
    ElementId,
    NodeKind,
    NodeShape,
    PropertyConstraint,
    ShapeSeverity,
    ShapeText,
)

__all__ = ["NodeKind", "NodeShape", "NodeShapeInput", "PropertyConstraint", "ShapeSeverity"]


class NodeShapeInput(BaseModel):
    """Create / replace payload; property constraint ids are minted when omitted."""

    model_config = ConfigDict(extra="forbid")

    target_class_id: ElementId
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: ShapeText = ""
    severity: ShapeSeverity = "Violation"
    message: ShapeText = ""
    deactivated: bool = False
    properties: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
