"""RDF view of knowledge-graph candidates and the SHACL / entailment lanes (Phase 4.2).

Only *asserted* triples of structurally projectable candidates are produced: entity types of
entities whose class exists in the version, relationships whose predicate exists and whose
endpoints were resolved, and attribute values (typed when the value parsed as the declared
datatype). Nothing inferred is ever added to the data graph. Results are mapped back to facts by
(focus node, path, value), to entities for node-level results, and via the shape index for
signature shapes.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from owlrl import OWLRL_Semantics
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from app.modules.kg.canonical import FactCandidate
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.policy import ValidationPolicy
from app.modules.kg.resolution import ResolutionResult, ResolvedEntity
from app.modules.kg.validation import Assessment, Check
from app.modules.ontology.domain import element_iri
from app.modules.shacl.engine import ShaclReport, ShaclResult, run_shacl, without_signature_shapes
from app.modules.shacl.shapes import ShapeIndex

_BUILTIN = tuple(str(ns) for ns in (RDF, RDFS, OWL, XSD))
Target = tuple[str, str]  # ("entity", vertex_id) | ("fact", fact.key)


def instance_iri(data_namespace: str, vertex_id: str) -> URIRef:
    return URIRef(f"{data_namespace}e/{vertex_id}")


@dataclass
class CandidateGraph:
    graph: Graph
    entity_by_iri: dict[str, str] = field(default_factory=dict)
    by_value: dict[tuple[str, str, str], list[str]] = field(default_factory=lambda: defaultdict(list))
    by_subject: dict[tuple[str, str], list[str]] = field(default_factory=lambda: defaultdict(list))
    by_object: dict[tuple[str, str], list[str]] = field(default_factory=lambda: defaultdict(list))
    prop_iri: dict[str, str] = field(default_factory=dict)
    iri_prop: dict[str, str] = field(default_factory=dict)


def build_candidate_graph(
    view: OntologyView,
    resolution: ResolutionResult,
    facts: list[FactCandidate],
    assessments: dict[str, tuple[Assessment, ResolvedEntity | None, ResolvedEntity | None]],
    data_namespace: str,
) -> CandidateGraph:
    namespace = view.snapshot.metadata.namespace
    graph = Graph(bind_namespaces="none")
    graph.bind("data", data_namespace + "e/")
    candidate = CandidateGraph(graph)
    class_iri = {c.id: URIRef(element_iri(namespace, c)) for c in view.snapshot.classes}
    for prop in (*view.snapshot.object_properties, *view.snapshot.datatype_properties):
        iri = element_iri(namespace, prop)
        candidate.prop_iri[prop.id] = iri
        candidate.iri_prop[iri] = prop.id

    for vertex_id, entity in resolution.entities.items():
        iri = instance_iri(data_namespace, vertex_id)
        candidate.entity_by_iri[str(iri)] = vertex_id
        if entity.class_id in class_iri:
            graph.add((iri, RDF.type, class_iri[entity.class_id]))

    for fact in facts:
        assessment, subject, obj = assessments[fact.key]
        if subject is None or fact.predicate_id not in candidate.prop_iri:
            continue
        s = instance_iri(data_namespace, subject.vertex_id)
        p = URIRef(candidate.prop_iri[fact.predicate_id])
        if fact.kind == "relationship":
            if obj is None or fact.predicate_id not in view.object_properties:
                continue
            o = instance_iri(data_namespace, obj.vertex_id)
            graph.add((s, p, o))
            candidate.by_value[(str(s), str(p), str(o))].append(fact.key)
            candidate.by_object[(str(o), str(p))].append(fact.key)
        else:
            prop = view.datatype_properties.get(fact.predicate_id or "")
            if prop is None:
                continue
            if assessment.canonical_value is not None:
                value = Literal(assessment.canonical_value, datatype=XSD[prop.datatype.value])
            else:
                value = Literal(fact.value or "")
            graph.add((s, p, value))
            candidate.by_value[(str(s), str(p), str(value))].append(fact.key)
        candidate.by_subject[(str(s), str(p))].append(fact.key)
    return candidate


def _targets(result: ShaclResult, candidate: CandidateGraph) -> list[Target]:
    shape = result.shape
    if shape is not None and shape.role == "signature" and shape.property_id:
        prop = candidate.prop_iri.get(shape.property_id, "")
        index = candidate.by_subject if shape.signature_side == "domain" else candidate.by_object
        return [("fact", key) for key in index.get((result.focus, prop), [])]
    if result.path and result.value is not None:
        keys = candidate.by_value.get((result.focus, result.path, result.value), [])
        if keys:
            return [("fact", key) for key in keys]
    if result.path and result.component == "MaxCountConstraintComponent":
        keys = candidate.by_subject.get((result.focus, result.path), [])
        if keys:
            return [("fact", key) for key in keys]
    vertex = candidate.entity_by_iri.get(result.focus)
    return [("entity", vertex)] if vertex else []


@dataclass
class LaneSummary:
    report: ShaclReport
    shapes_source: str
    results_by_outcome: dict[str, int] = field(default_factory=dict)
    unmapped_results: int = 0
    inconsistencies: list[str] = field(default_factory=list)
    inferred_type_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "conforms": self.report.conforms,
            "results": len(self.report.results),
            "by_severity": self.report.by_severity(),
            "by_outcome": self.results_by_outcome,
            "unmapped_results": self.unmapped_results,
            "shapes_source": self.shapes_source,
            "shapes_used": self.report.shapes_used,
            "duration_ms": self.report.duration_ms,
            "inconsistencies": self.inconsistencies,
            "inferred_types": self.inferred_type_count,
        }


def run_lanes(
    *,
    view: OntologyView,
    policy: ValidationPolicy,
    candidate: CandidateGraph,
    shapes: Graph,
    index: ShapeIndex,
    ontology: Graph,
    shapes_source: str,
    entity_assessments: dict[str, Assessment],
    fact_items: dict[str, tuple[FactCandidate, Assessment, ResolvedEntity | None, ResolvedEntity | None]],
) -> LaneSummary:
    """Run SHACL (and, when the policy asks for it, entailment); attach results to assessments."""
    fact_assessments = {key: item[1] for key, item in fact_items.items()}
    for assessment in (*entity_assessments.values(), *fact_assessments.values()):
        assessment.policy = policy
    active_shapes = shapes if policy.use_signature_shapes else without_signature_shapes(shapes)
    report = run_shacl(candidate.graph, active_shapes, ontology, index)
    summary = LaneSummary(report=report, shapes_source=shapes_source)
    for result in report.results:
        shape = result.shape
        outcome = policy.shacl_outcome(
            severity=result.severity,
            component=result.component,
            origin=shape.origin if shape else "preserved",
            role=shape.role if shape else "constraint",
        )
        summary.results_by_outcome[outcome] = summary.results_by_outcome.get(outcome, 0) + 1
        entry = {**result.as_dict(), "outcome": outcome}
        targets = _targets(result, candidate)
        if not targets:
            summary.unmapped_results += 1
        for kind, key in targets:
            assessment = entity_assessments.get(key) if kind == "entity" else fact_assessments.get(key)
            if assessment is not None:
                assessment.shacl.append(entry)

    if policy.entailment:
        _entailment_lane(view, candidate, ontology, entity_assessments, fact_items, summary)
    return summary


def _entailment_lane(
    view: OntologyView,
    candidate: CandidateGraph,
    ontology: Graph,
    entity_assessments: dict[str, Assessment],
    fact_items: dict[str, tuple[FactCandidate, Assessment, ResolvedEntity | None, ResolvedEntity | None]],
    summary: LaneSummary,
) -> None:
    """OWL 2 RL over ontology + asserted candidates. Inferred triples are reported, never persisted.

    A fact whose domain/range check was relaxed by the policy is quarantined when the type it implies
    for an endpoint is incompatible with the endpoint's asserted class (neither a superclass nor a
    subclass), or when the endpoint takes part in an OWL 2 RL inconsistency; a compatible implication
    (a refinement) is accepted and recorded.
    """
    working = Graph(bind_namespaces="none")
    for triple in (*ontology, *candidate.graph):
        working.add(triple)
    closure = OWLRL_Semantics(working, False, False, rdfs=False)
    closure.closure()
    messages = [str(m) for m in closure.error_messages]
    summary.inconsistencies = messages
    class_label = {
        element_iri(view.snapshot.metadata.namespace, c): c.label for c in view.snapshot.classes
    }
    for iri, vertex_id in candidate.entity_by_iri.items():
        subject = URIRef(iri)
        asserted = set(candidate.graph.objects(subject, RDF.type))
        inferred = sorted(
            class_label.get(str(o), str(o))
            for o in working.objects(subject, RDF.type)
            if isinstance(o, URIRef) and o not in asserted and not str(o).startswith(_BUILTIN)
        )
        involved = [m for m in messages if iri in m]
        assessment = entity_assessments.get(vertex_id)
        if assessment is not None:
            assessment.inferred_types = inferred
            summary.inferred_type_count += len(inferred)
            for message in involved:
                assessment.entailment.append(Check("consistent", False, f"OWL 2 RL inconsistency: {message}"))
        for key in (*_facts_of(candidate.by_subject, iri), *_facts_of(candidate.by_object, iri)):
            item = fact_items.get(key)
            if item is None:
                continue
            for message in involved:
                item[1].entailment.append(Check("consistent", False, f"OWL 2 RL inconsistency involving this fact: {message}"))

    for fact, assessment, subject, obj in fact_items.values():
        relaxed = [c for c in assessment.structural if not c.passed and c.code in ("domain", "range", "direction")]
        if not relaxed:
            continue
        prop = view.object_properties.get(fact.predicate_id or "") or view.datatype_properties.get(fact.predicate_id or "")
        if prop is None:
            continue
        implications = [(subject, prop.domain_id, "subject")]
        if fact.kind == "relationship":
            implications.append((obj, getattr(prop, "range_id", None), "object"))
        for entity, implied, role in implications:
            if entity is None or not implied or not entity.class_id or view.is_a(entity.class_id, implied):
                continue
            asserted, implied_label = view.class_label(entity.class_id), view.class_label(implied)
            assessment.inferred_types.append(f"{entity.label} is a {implied_label}")
            if view.is_a(implied, entity.class_id):
                assessment.entailment.append(
                    Check(f"{role}_type_refined", True, f"Implies that {entity.label} ({asserted}) is a {implied_label} (a subclass).")
                )
            else:
                assessment.entailment.append(
                    Check(
                        f"{role}_type_compatible",
                        False,
                        f"Suspicious: '{prop.label}' implies that {entity.label} ({asserted}) is also a {implied_label}, "
                        f"which is neither a superclass nor a subclass of {asserted}.",
                    )
                )


def _facts_of(index: dict[tuple[str, str], list[str]], iri: str) -> list[str]:
    return [key for (node, _), keys in index.items() if node == iri for key in keys]
