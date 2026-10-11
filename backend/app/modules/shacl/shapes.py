"""Shapes graph of an ontology snapshot: generated, authored and preserved SHACL.

The graph is deterministic for a given snapshot, so a version's ``shapes.ttl`` can be materialised
at publication time and never depends on later generator changes. :class:`ShapeIndex` maps shape
IRIs back to ontology elements so validation results can be reported against facts and entities.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from rdflib import BNode, Graph, Literal as RdfLiteral, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SH, XSD

from app.modules.ontology.domain import (
    DatatypePropertyDefinition,
    NodeShape,
    ObjectPropertyDefinition,
    PropertyConstraint,
)
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.semantics.graphs import load_ntriples
from app.modules.semantics.owl import element_iris, ontology_iri_of

OLS = Namespace("urn:ols:vocab#")
Origin = Literal["generated", "authored", "preserved"]
Role = Literal["constraint", "signature"]


@dataclass(frozen=True)
class ShapeInfo:
    iri: str
    origin: Origin
    role: Role
    label: str
    shape_id: str | None = None
    target_class_id: str | None = None
    property_id: str | None = None
    signature_side: Literal["domain", "range"] | None = None


@dataclass
class ShapeIndex:
    shapes: dict[str, ShapeInfo] = field(default_factory=dict)

    def add(self, info: ShapeInfo) -> None:
        self.shapes[info.iri] = info

    def get(self, iri: str) -> ShapeInfo | None:
        return self.shapes.get(iri)

    def iris(self, *, role: Role | None = None, origin: Origin | None = None) -> list[str]:
        return [
            i.iri
            for i in self.shapes.values()
            if (role is None or i.role == role) and (origin is None or i.origin == origin)
        ]

    def counts(self) -> dict[str, int]:
        node_shapes = [i for i in self.shapes.values() if i.property_id is None or i.role == "signature"]
        counter = Counter(f"{i.origin}_{i.role}" for i in node_shapes)
        return dict(sorted(counter.items()))


def shapes_namespace(snapshot: OntologySnapshot) -> Namespace:
    return Namespace(f"{ontology_iri_of(snapshot)}/shapes#")


def _typed(value: str, datatype: str | None) -> RdfLiteral:
    return RdfLiteral(value, datatype=XSD[datatype]) if datatype else RdfLiteral(value)


class _Builder:
    def __init__(self, snapshot: OntologySnapshot) -> None:
        self.snapshot = snapshot
        self.graph = Graph(bind_namespaces="none")
        self.index = ShapeIndex()
        self.ns = shapes_namespace(snapshot)
        self.iris = element_iris(snapshot)
        self.classes = {c.id: c for c in snapshot.classes}
        self.object_properties = {p.id: p for p in snapshot.object_properties}
        self.datatype_properties = {p.id: p for p in snapshot.datatype_properties}
        for prefix, namespace in (("sh", SH), ("xsd", XSD), ("rdf", RDF), ("rdfs", RDFS), ("owl", OWL), ("ols", OLS)):
            self.graph.bind(prefix, namespace)
        self.graph.bind(snapshot.metadata.prefix, Namespace(snapshot.metadata.namespace))
        self.graph.bind(f"{snapshot.metadata.prefix}sh", self.ns)

    def add(self, *triple: object) -> None:
        self.graph.add(triple)  # type: ignore[arg-type]

    # -------------------------------------------------------------------------- generated

    def generated(self) -> None:
        props_by_domain: dict[str, list[ObjectPropertyDefinition | DatatypePropertyDefinition]] = {}
        for prop in (*self.snapshot.datatype_properties, *self.snapshot.object_properties):
            if prop.domain_id in self.classes:
                props_by_domain.setdefault(prop.domain_id, []).append(prop)
        for cls in sorted(self.snapshot.classes, key=lambda c: c.id):
            props = sorted(props_by_domain.get(cls.id, []), key=lambda p: p.id)
            constraints = [(p, self._generated_constraint(p)) for p in props]
            constraints = [(p, c) for p, c in constraints if c]
            if not constraints:
                continue
            node = self.ns[f"g-{cls.id}"]
            self.add(node, RDF.type, SH.NodeShape)
            self.add(node, SH.targetClass, self.iris[cls.id])
            self.add(node, RDFS.label, RdfLiteral(f"{cls.label} (generated)"))
            self.add(node, OLS.generated, RdfLiteral(True))
            self.add(node, OLS.shapeRole, RdfLiteral("constraint"))
            self.index.add(ShapeInfo(str(node), "generated", "constraint", f"{cls.label} (generated)", target_class_id=cls.id))
            for prop, values in constraints:
                shape = self.ns[f"g-{cls.id}-{prop.id}"]
                self.add(node, SH.property, shape)
                self.add(shape, SH.path, self.iris[prop.id])
                self.add(shape, SH.name, RdfLiteral(prop.label))
                for predicate, obj in values:
                    self.add(shape, predicate, obj)
                self.index.add(
                    ShapeInfo(
                        str(shape), "generated", "constraint", f"{cls.label} · {prop.label}",
                        target_class_id=cls.id, property_id=prop.id,
                    )
                )
        self._signatures()

    def _generated_constraint(self, prop: ObjectPropertyDefinition | DatatypePropertyDefinition) -> list[tuple[URIRef, object]]:
        values: list[tuple[URIRef, object]] = []
        if isinstance(prop, DatatypePropertyDefinition):
            if prop.semantics.range_declared:
                values.append((SH.datatype, XSD[prop.datatype.value]))
            if prop.required:
                values.append((SH.minCount, RdfLiteral(1)))
            if not prop.multi_valued:
                values.append((SH.maxCount, RdfLiteral(1)))
        elif prop.range_id in self.iris:
            values.append((SH["class"], self.iris[prop.range_id]))
        return values

    def _signatures(self) -> None:
        for prop in sorted((*self.snapshot.object_properties, *self.snapshot.datatype_properties), key=lambda p: p.id):
            sides: list[tuple[Literal["domain", "range"], URIRef, str | None]] = [("domain", SH.targetSubjectsOf, prop.domain_id)]
            if isinstance(prop, ObjectPropertyDefinition):
                sides.append(("range", SH.targetObjectsOf, prop.range_id))
            for side, target, class_id in sides:
                if class_id not in self.classes:
                    continue
                node = self.ns[f"sig-{side}-{prop.id}"]
                cls = self.classes[class_id]
                role_text = "Subjects" if side == "domain" else "Objects"
                self.add(node, RDF.type, SH.NodeShape)
                self.add(node, target, self.iris[prop.id])
                self.add(node, SH["class"], self.iris[class_id])
                self.add(node, RDFS.label, RdfLiteral(f"{prop.label}: {side} {cls.label}"))
                self.add(node, SH.message, RdfLiteral(f"{role_text} of '{prop.label}' must be instances of {cls.label}."))
                self.add(node, OLS.generated, RdfLiteral(True))
                self.add(node, OLS.shapeRole, RdfLiteral("signature"))
                self.index.add(
                    ShapeInfo(
                        str(node), "generated", "signature", f"{prop.label}: {side} {cls.label}",
                        target_class_id=class_id, property_id=prop.id, signature_side=side,
                    )
                )

    # -------------------------------------------------------------------------- authored

    def authored(self) -> None:
        for shape in sorted(self.snapshot.shapes, key=lambda s: s.id):
            self._authored_shape(shape)

    def _authored_shape(self, shape: NodeShape) -> None:
        if shape.target_class_id not in self.iris:
            return
        node = self.ns[f"a-{shape.id}"]
        self.add(node, RDF.type, SH.NodeShape)
        self.add(node, SH.targetClass, self.iris[shape.target_class_id])
        self.add(node, RDFS.label, RdfLiteral(shape.label))
        if shape.description:
            self.add(node, RDFS.comment, RdfLiteral(shape.description))
        self.add(node, SH.severity, SH[shape.severity])
        if shape.message:
            self.add(node, SH.message, RdfLiteral(shape.message))
        if shape.deactivated:
            self.add(node, SH.deactivated, RdfLiteral(True))
        self.add(node, OLS.shapeRole, RdfLiteral("constraint"))
        self.index.add(ShapeInfo(str(node), "authored", "constraint", shape.label, shape_id=shape.id, target_class_id=shape.target_class_id))
        for constraint in shape.properties:
            if constraint.path_id not in self.iris:
                continue
            prop_shape = self.ns[f"a-{shape.id}-{constraint.id}"]
            self.add(node, SH.property, prop_shape)
            self._constraint(prop_shape, constraint, shape)
            label = self.object_properties.get(constraint.path_id) or self.datatype_properties.get(constraint.path_id)
            self.index.add(
                ShapeInfo(
                    str(prop_shape), "authored", "constraint", f"{shape.label} · {label.label if label else constraint.path_id}",
                    shape_id=shape.id, target_class_id=shape.target_class_id, property_id=constraint.path_id,
                )
            )

    def _constraint(self, node: URIRef, c: PropertyConstraint, shape: NodeShape) -> None:
        self.add(node, SH.path, self.iris[c.path_id])
        prop = self.datatype_properties.get(c.path_id)
        datatype = (c.datatype or (prop.datatype if prop else None))
        datatype_name = datatype.value if datatype else None
        self.add(node, SH.severity, SH[c.severity or shape.severity])
        if c.message or shape.message:
            self.add(node, SH.message, RdfLiteral(c.message or shape.message))
        if c.min_count is not None:
            self.add(node, SH.minCount, RdfLiteral(c.min_count))
        if c.max_count is not None:
            self.add(node, SH.maxCount, RdfLiteral(c.max_count))
        if c.datatype:
            self.add(node, SH.datatype, XSD[c.datatype.value])
        if c.class_id and c.class_id in self.iris:
            self.add(node, SH["class"], self.iris[c.class_id])
        if c.node_kind:
            self.add(node, SH.nodeKind, SH[c.node_kind])
        if c.allowed_values:
            head = BNode()
            items = (
                [URIRef(v) for v in c.allowed_values]
                if c.path_id in self.object_properties
                else [_typed(v, datatype_name) for v in c.allowed_values]
            )
            Collection(self.graph, head, items)
            self.add(node, SH["in"], head)
        if c.pattern:
            self.add(node, SH.pattern, RdfLiteral(c.pattern))
        if c.min_length is not None:
            self.add(node, SH.minLength, RdfLiteral(c.min_length))
        if c.max_length is not None:
            self.add(node, SH.maxLength, RdfLiteral(c.max_length))
        if c.min_inclusive is not None:
            self.add(node, SH.minInclusive, _typed(c.min_inclusive, datatype_name))
        if c.max_inclusive is not None:
            self.add(node, SH.maxInclusive, _typed(c.max_inclusive, datatype_name))

    # -------------------------------------------------------------------------- preserved

    def preserved(self) -> None:
        for axiom in self.snapshot.extension_axioms:
            if axiom.scope != "shapes":
                continue
            before = set(self.graph.subjects(RDF.type, SH.NodeShape)) | set(self.graph.subjects(RDF.type, SH.PropertyShape))
            load_ntriples(self.graph, axiom.ntriples)
            after = set(self.graph.subjects(RDF.type, SH.NodeShape)) | set(self.graph.subjects(RDF.type, SH.PropertyShape))
            for node in sorted(after - before, key=str):
                if isinstance(node, URIRef):
                    self.index.add(ShapeInfo(str(node), "preserved", "constraint", axiom.summary[:200]))


def build_shapes_graph(
    snapshot: OntologySnapshot,
    *,
    generated: bool = True,
    authored: bool = True,
    preserved: bool = True,
) -> tuple[Graph, ShapeIndex]:
    builder = _Builder(snapshot)
    if generated:
        builder.generated()
    if authored:
        builder.authored()
    if preserved:
        builder.preserved()
    return builder.graph, builder.index


def index_shapes_graph(graph: Graph, snapshot: OntologySnapshot) -> ShapeIndex:
    """Rebuild the index for a stored (materialised) ``shapes.ttl`` using the snapshot's elements."""
    _, index = build_shapes_graph(snapshot)
    stored = ShapeIndex()
    known = index.shapes
    for node in set(graph.subjects(RDF.type, SH.NodeShape)) | set(graph.subjects(SH.path, None)):
        iri = str(node)
        if iri in known:
            stored.add(known[iri])
        elif isinstance(node, URIRef):
            role = graph.value(node, OLS.shapeRole)
            stored.add(ShapeInfo(iri, "preserved", "signature" if str(role) == "signature" else "constraint", iri))
    return stored
