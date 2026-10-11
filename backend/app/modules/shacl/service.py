"""Authored SHACL shapes of ontology drafts, the draft shapes graph and sample-data validation."""

import hashlib
from collections import defaultdict
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SH, XSD
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import new_element_id, new_id
from app.modules.ontology.domain import NodeShape, PropertyConstraint, element_iri
from app.modules.ontology.models import Ontology, OntologyExtensionAxiomRecord, OntologyShapeRecord
from app.modules.ontology.service import OntologyService
from app.modules.registry.snapshot import OntologySnapshot, build_snapshot, metadata_from_ontology
from app.modules.semantics.graphs import (
    FORMATS,
    FormatInfo,
    bnode_components,
    canonical_ntriples,
    detect_format,
    has_bnode,
    parse_rdf,
    serialize,
    to_ntriples,
)
from app.modules.semantics.owl import snapshot_to_owl
from app.modules.shacl.engine import check_shapes, run_shacl, without_signature_shapes
from app.modules.shacl.model import NodeShapeInput
from app.modules.shacl.schemas import (
    GeneratedConstraintRead,
    GeneratedShapeRead,
    PreservedShapeRead,
    SampleValidationRequest,
    ShaclValidationResponse,
    ShapesImportResponse,
    ShapesOverview,
    SignatureShapeRead,
)
from app.modules.shacl.shapes import ShapeIndex, build_shapes_graph


def _int(graph: Graph, node: URIRef, predicate: URIRef) -> int | None:
    value = graph.value(node, predicate)
    return int(value) if value is not None else None


def generated_overview(
    snapshot: OntologySnapshot, graph: Graph, index: ShapeIndex
) -> tuple[list[GeneratedShapeRead], list[SignatureShapeRead]]:
    labels = {e.id: e.label for e in (*snapshot.object_properties, *snapshot.datatype_properties)}
    datatype_ids = {p.id for p in snapshot.datatype_properties}
    class_by_iri = {element_iri(snapshot.metadata.namespace, c): c.id for c in snapshot.classes}
    nodes: dict[str, GeneratedShapeRead] = {}
    constraints: dict[str, list[GeneratedConstraintRead]] = defaultdict(list)
    signatures: list[SignatureShapeRead] = []
    for info in index.shapes.values():
        if info.origin != "generated":
            continue
        if info.role == "signature":
            signatures.append(
                SignatureShapeRead(
                    iri=info.iri,
                    property_id=info.property_id or "",
                    side=info.signature_side or "domain",
                    class_id=info.target_class_id or "",
                    label=info.label,
                )
            )
        elif info.property_id is None:
            nodes[info.target_class_id or ""] = GeneratedShapeRead(
                iri=info.iri, target_class_id=info.target_class_id or "", label=info.label, constraints=[]
            )
        else:
            node = URIRef(info.iri)
            datatype = graph.value(node, SH.datatype)
            cls = graph.value(node, SH["class"])
            constraints[info.target_class_id or ""].append(
                GeneratedConstraintRead(
                    iri=info.iri,
                    property_id=info.property_id,
                    property_label=labels.get(info.property_id, info.property_id),
                    kind="attribute" if info.property_id in datatype_ids else "relationship",
                    datatype=str(datatype).removeprefix(str(XSD)) if datatype is not None else None,
                    min_count=_int(graph, node, SH.minCount),
                    max_count=_int(graph, node, SH.maxCount),
                    class_id=class_by_iri.get(str(cls)) if cls is not None else None,
                )
            )
    for class_id, node in nodes.items():
        node.constraints = sorted(constraints.get(class_id, []), key=lambda c: c.property_label.lower())
    return (
        sorted(nodes.values(), key=lambda n: n.label.lower()),
        sorted(signatures, key=lambda s: (s.label.lower(), s.side)),
    )


class ShapeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.ontologies = OntologyService(session)

    # ------------------------------------------------------------------------------ helpers

    def draft_snapshot(self, ontology_id: str) -> tuple[Ontology, OntologySnapshot]:
        ontology, schema = self.ontologies.get_schema(ontology_id)
        return ontology, build_snapshot(metadata_from_ontology(ontology), schema)

    def _record(self, ontology_id: str, shape_id: str) -> OntologyShapeRecord:
        record = self.session.get(OntologyShapeRecord, {"ontology_id": ontology_id, "id": shape_id})
        if record is None:
            raise NotFoundError(f"Shape '{shape_id}' was not found.", code="SHAPE_NOT_FOUND")
        return record

    def _validated(self, ontology_id: str, shape_id: str, data: NodeShapeInput) -> NodeShape:
        properties = []
        for raw in data.properties:
            item = dict(raw)
            item.setdefault("id", new_element_id("pc"))
            if not item.get("id"):
                item["id"] = new_element_id("pc")
            properties.append(item)
        try:
            shape = NodeShape(
                id=shape_id,
                target_class_id=data.target_class_id,
                label=data.label,
                description=data.description,
                severity=data.severity,
                message=data.message,
                deactivated=data.deactivated,
                properties=[PropertyConstraint.model_validate(p) for p in properties],
            )
        except PydanticValidationError as exc:
            raise BusinessRuleError(
                "The shape is not valid.",
                code="SHAPE_INVALID",
                details={"errors": exc.errors(include_url=False, include_context=False)},
            ) from exc
        _, schema = self.ontologies.get_schema(ontology_id)
        class_ids = {c.id for c in schema.classes}
        object_ids = {p.id for p in schema.object_properties}
        datatype_ids = {p.id for p in schema.datatype_properties}
        problems: list[str] = []
        if shape.target_class_id not in class_ids:
            problems.append(f"Target class '{shape.target_class_id}' does not exist.")
        ids = [c.id for c in shape.properties]
        if len(ids) != len(set(ids)):
            problems.append("Property constraint ids must be unique within a shape.")
        for constraint in shape.properties:
            if constraint.path_id not in object_ids | datatype_ids:
                problems.append(f"Property '{constraint.path_id}' does not exist.")
            if constraint.class_id and (constraint.path_id not in object_ids or constraint.class_id not in class_ids):
                problems.append("A class constraint needs a relationship path and an existing class.")
            if constraint.datatype and constraint.path_id in object_ids:
                problems.append("A datatype constraint needs an attribute path.")
            if constraint.is_empty():
                problems.append(f"The constraint on '{constraint.path_id}' has no condition.")
        if problems:
            raise BusinessRuleError(problems[0], code="SHAPE_INVALID", details={"problems": problems})
        return shape

    def _audit(self, ontology: Ontology, event: str, summary: str, actor: str, details: dict[str, Any]) -> None:
        self.ontologies._touch(ontology)
        self.ontologies._activity(ontology, event, summary, {"actor": actor, **details})

    # ------------------------------------------------------------------------------ queries

    def overview(self, ontology_id: str) -> ShapesOverview:
        ontology, snapshot = self.draft_snapshot(ontology_id)
        graph, index = build_shapes_graph(snapshot)
        generated, signatures = generated_overview(snapshot, graph, index)
        element_ids = {e.id for e in (*snapshot.classes, *snapshot.object_properties, *snapshot.datatype_properties)}
        preserved = [
            PreservedShapeRead(
                axiom_id=a.id,
                kind=a.kind,
                summary=a.summary,
                ntriples=a.ntriples,
                anchor_ids=a.anchor_ids,
                orphaned=any(i not in element_ids for i in a.anchor_ids),
            )
            for a in snapshot.extension_axioms
            if a.scope == "shapes"
        ]
        return ShapesOverview(
            ontology_id=ontology_id,
            draft_revision=ontology.draft_revision,
            authored=snapshot.shapes,
            generated=generated,
            signatures=signatures,
            preserved=preserved,
            check=check_shapes(graph),
            triple_count=len(graph),
        )

    def export(self, ontology_id: str, rdf_format: str) -> tuple[bytes, FormatInfo, str]:
        ontology, snapshot = self.draft_snapshot(ontology_id)
        graph, _ = build_shapes_graph(snapshot)
        info = FORMATS[rdf_format]
        return serialize(graph, rdf_format), info, f"{ontology.prefix}-draft-r{ontology.draft_revision}-shapes.{info.extension}"

    def validate_sample(self, ontology_id: str, request: SampleValidationRequest) -> ShaclValidationResponse:
        _, snapshot = self.draft_snapshot(ontology_id)
        data = parse_rdf(request.data.encode("utf-8"), request.rdf_format)
        shapes, index = build_shapes_graph(snapshot)
        if not request.include_signature_shapes:
            shapes = without_signature_shapes(shapes)
        report = run_shacl(data, shapes, snapshot_to_owl(snapshot, include_axioms=False), index)
        return ShaclValidationResponse(
            conforms=report.conforms,
            data_triples=len(data),
            shapes_used=report.shapes_used,
            duration_ms=report.duration_ms,
            by_severity=report.by_severity(),
            results=[r.as_dict() for r in report.results],
        )

    # ------------------------------------------------------------------------------ commands

    def create(self, ontology_id: str, data: NodeShapeInput, actor: str) -> NodeShape:
        ontology = self.ontologies._require(ontology_id)
        shape = self._validated(ontology_id, new_element_id("shp"), data)
        order = len(self.ontologies.repo.shapes(ontology_id))
        self.session.add(
            OntologyShapeRecord(
                ontology_id=ontology_id,
                sort_order=order,
                **shape.model_dump(mode="json", exclude={"properties"}),
                properties=[p.model_dump(mode="json", exclude_none=True) for p in shape.properties],
            )
        )
        self._audit(ontology, "ontology.shape_created", f"SHACL shape '{shape.label}' added", actor, {"shape_id": shape.id})
        self.session.commit()
        return shape

    def update(self, ontology_id: str, shape_id: str, data: NodeShapeInput, actor: str) -> NodeShape:
        ontology = self.ontologies._require(ontology_id)
        record = self._record(ontology_id, shape_id)
        shape = self._validated(ontology_id, shape_id, data)
        values = shape.model_dump(mode="json", exclude={"id", "properties"})
        values["properties"] = [p.model_dump(mode="json", exclude_none=True) for p in shape.properties]
        changed = {k: v for k, v in values.items() if getattr(record, k) != v}
        if changed:
            for key, value in changed.items():
                setattr(record, key, value)
            self._audit(
                ontology,
                "ontology.shape_updated",
                f"SHACL shape '{shape.label}' updated ({', '.join(sorted(changed))})",
                actor,
                {"shape_id": shape_id},
            )
            self.session.commit()
        return shape

    def delete(self, ontology_id: str, shape_id: str, actor: str) -> None:
        ontology = self.ontologies._require(ontology_id)
        record = self._record(ontology_id, shape_id)
        label = record.label
        self.session.delete(record)
        self._audit(ontology, "ontology.shape_deleted", f"SHACL shape '{label}' deleted", actor, {"shape_id": shape_id})
        self.session.commit()

    def import_shapes(self, ontology_id: str, *, filename: str, data: bytes, rdf_format: str | None, actor: str) -> ShapesImportResponse:
        """Import SHACL into the draft as preserved shapes (verbatim, enforced, never reinterpreted)."""
        ontology = self.ontologies._require(ontology_id)
        fmt = detect_format(filename, rdf_format)
        graph = parse_rdf(data, fmt)
        if not any(graph.subjects(RDF.type, SH.NodeShape)) and not any(graph.subjects(RDF.type, SH.PropertyShape)):
            raise BusinessRuleError("The document contains no sh:NodeShape or sh:PropertyShape.", code="SHAPES_NOT_FOUND")
        check = check_shapes(graph)
        if not check.well_formed:
            raise BusinessRuleError(
                "The shapes are not well formed (SHACL-SHACL meta-validation failed).",
                code="SHAPES_INVALID",
                details={"report": check.message[:4000]},
            )
        _, snapshot = self.draft_snapshot(ontology_id)
        id_by_iri = {
            element_iri(snapshot.metadata.namespace, e): e.id
            for e in (*snapshot.classes, *snapshot.object_properties, *snapshot.datatype_properties)
        }
        existing = {canonical_ntriples(a.ntriples) for a in snapshot.extension_axioms if a.scope == "shapes"}
        groups: dict[Any, list[Any]] = defaultdict(list)
        # One preserved axiom per named shape (its ground triples plus blank-node property shapes).
        for component in bnode_components(graph):
            anchor = next((t[0] for t in component if isinstance(t[0], URIRef)), None)
            groups[("subject", anchor) if anchor is not None else ("component", len(groups))].extend(component)
        created: list[PreservedShapeRead] = []
        order = len(self.ontologies.repo.extension_axioms(ontology_id))
        for triples in groups.values():
            ntriples = to_ntriples(triples)
            if canonical_ntriples(ntriples) in existing:
                continue
            anchors = sorted({id_by_iri[str(t)] for tr in triples for t in tr if isinstance(t, URIRef) and str(t) in id_by_iri})
            first = sorted(triples, key=lambda t: (has_bnode(t), str(t[1])))[0]
            summary = f"{first[0].n3(graph.namespace_manager)} {first[1].n3(graph.namespace_manager)} ..."[:300]
            record = OntologyExtensionAxiomRecord(
                id=new_id(),
                ontology_id=ontology_id,
                scope="shapes",
                kind="shacl-shape",
                summary=summary + f" ({len(triples)} triples)",
                ntriples=ntriples,
                anchor_ids=anchors,
                sort_order=order,
            )
            order += 1
            self.session.add(record)
            created.append(
                PreservedShapeRead(
                    axiom_id=record.id, kind=record.kind, summary=record.summary, ntriples=ntriples,
                    anchor_ids=anchors, orphaned=False,
                )
            )
        if not created:
            raise ConflictError("Every shape in the document is already part of the draft.", code="SHAPES_ALREADY_PRESENT")
        self._audit(
            ontology,
            "ontology.shapes_imported",
            f"{len(created)} SHACL shape group(s) imported from {filename}",
            actor,
            {"sha256": hashlib.sha256(data).hexdigest(), "groups": len(created)},
        )
        self.session.commit()
        return ShapesImportResponse(preserved=created, triples=len(graph))
