"""PySHACL engine wrapper.

Validation **never** runs RDFS/OWL inference over the data graph (``inference="none"``): with
inference enabled, a reversed relationship would first entail the expected types and then pass the
very shapes meant to catch it. The ontology graph is mixed in (``ont_graph``) only so that
``sh:class`` and ``sh:targetClass`` respect ``rdfs:subClassOf``.
"""

import time
from dataclasses import dataclass, field
from typing import Literal

from pyshacl import validate as pyshacl_validate
from pyshacl.errors import ReportableRuntimeError
from pydantic import BaseModel
from rdflib import BNode, Graph, Literal as RdfLiteral, URIRef
from rdflib.namespace import RDF, SH

from app.modules.shacl.shapes import OLS, ShapeIndex, ShapeInfo

Severity = Literal["Violation", "Warning", "Info"]


@dataclass
class ShaclResult:
    focus: str
    path: str | None
    value: str | None
    value_is_literal: bool
    severity: Severity
    component: str
    source_shape: str
    message: str
    shape: ShapeInfo | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "focus": self.focus,
            "path": self.path,
            "value": self.value,
            "severity": self.severity,
            "component": self.component,
            "source_shape": self.source_shape,
            "shape_label": self.shape.label if self.shape else None,
            "shape_origin": self.shape.origin if self.shape else "preserved",
            "shape_role": self.shape.role if self.shape else "constraint",
            "message": self.message,
        }


@dataclass
class ShaclReport:
    conforms: bool
    results: list[ShaclResult] = field(default_factory=list)
    duration_ms: int = 0
    shapes_used: int = 0

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.severity] = counts.get(result.severity, 0) + 1
        return counts


class ShapesCheck(BaseModel):
    """SHACL-SHACL meta-validation of a shapes graph (are the shapes themselves well formed?)."""

    well_formed: bool
    message: str = ""


def without_signature_shapes(shapes: Graph) -> Graph:
    filtered = Graph(bind_namespaces="none")
    signature = {s for s in shapes.subjects(OLS.shapeRole, RdfLiteral("signature"))}
    for triple in shapes:
        if triple[0] not in signature:
            filtered.add(triple)
    return filtered


def check_shapes(shapes: Graph) -> ShapesCheck:
    # PySHACL's meta-validation adds SHACL-SHACL vocabulary triples to the graph it is given: validate a copy.
    working = Graph(bind_namespaces="none")
    for triple in shapes:
        working.add(triple)
    try:
        pyshacl_validate(Graph(), shacl_graph=working, meta_shacl=True, inference="none")
    except ReportableRuntimeError as error:
        return ShapesCheck(well_formed=False, message=str(error.message if hasattr(error, "message") else error))
    return ShapesCheck(well_formed=True)


def _local(term: object) -> str:
    text = str(term)
    return text.rsplit("#", 1)[-1] if "#" in text else text.rsplit("/", 1)[-1]


def run_shacl(data: Graph, shapes: Graph, ontology: Graph | None, index: ShapeIndex) -> ShaclReport:
    started = time.perf_counter()
    # PySHACL adds vocabulary axioms (e.g. owl:Class rdfs:subClassOf rdfs:Class) to the shapes graph it
    # receives; stored or cached shapes graphs must stay byte-for-byte what was published.
    working_shapes = Graph(bind_namespaces="none")
    for triple in shapes:
        working_shapes.add(triple)
    conforms, results_graph, _ = pyshacl_validate(
        data,
        shacl_graph=working_shapes,
        ont_graph=ontology,
        inference="none",
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=True,
        advanced=False,
    )
    results: list[ShaclResult] = []
    for node in results_graph.subjects(RDF.type, SH.ValidationResult):
        focus = results_graph.value(node, SH.focusNode)
        path = results_graph.value(node, SH.resultPath)
        value = results_graph.value(node, SH.value)
        severity = results_graph.value(node, SH.resultSeverity)
        component = results_graph.value(node, SH.sourceConstraintComponent)
        source = results_graph.value(node, SH.sourceShape)
        message = results_graph.value(node, SH.resultMessage)
        source_iri = str(source) if isinstance(source, URIRef) else f"_:{source}" if isinstance(source, BNode) else ""
        results.append(
            ShaclResult(
                focus=str(focus),
                path=str(path) if isinstance(path, URIRef) else None,
                value=str(value) if value is not None else None,
                value_is_literal=isinstance(value, RdfLiteral),
                severity=_local(severity) if severity is not None else "Violation",  # type: ignore[arg-type]
                component=_local(component) if component is not None else "",
                source_shape=source_iri,
                message=str(message) if message is not None else "",
                shape=index.get(source_iri),
            )
        )
    results.sort(key=lambda r: (r.focus, r.path or "", r.component, r.value or ""))
    return ShaclReport(
        conforms=bool(conforms),
        results=results,
        duration_ms=int((time.perf_counter() - started) * 1000),
        shapes_used=len(set(shapes.subjects(RDF.type, SH.NodeShape))),
    )
