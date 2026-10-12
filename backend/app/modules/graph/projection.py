"""Deterministic projections of a build's accepted facts (Phase 4.4).

* :func:`project_property_graph` - vertices and edges (the Phase 3 graph-persistence logic, moved
  here unchanged so builds and deployments share it).
* :func:`project_rdf` - RDF quads: a data named graph per build (instance IRIs
  ``{data_namespace}e/{vertex_id}``, ``rdf:type``, typed literals, relationships with property
  IRIs), a companion provenance graph (fact and source ids per element; works on every SPARQL 1.1
  store, no RDF-star needed) and the ontology graph of the published version.

Projections are pure functions of (accepted facts, ontology version, data namespace): equal inputs
produce equal outputs, so re-deployment is idempotent.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

from app.modules.graph.store import GraphEdge, GraphVertex
from app.modules.ontology.domain import element_iri
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.semantics.owl import snapshot_to_owl

OLS = Namespace("urn:ols:vocab#")


def edge_id(out_id: str, predicate_id: str, in_id: str) -> str:
    return "e" + hashlib.sha1(f"{out_id}|{predicate_id}|{in_id}".encode()).hexdigest()[:24]


# ---------------------------------------------------------------------------------- property graph


@dataclass
class PropertyGraphProjection:
    vertices: list[GraphVertex]
    edges: list[GraphEdge]
    element_of_fact: dict[str, str] = field(default_factory=dict)
    skipped_relationships: int = 0

    @property
    def merged_duplicate_facts(self) -> int:
        return sum(len(e.fact_ids) - 1 for e in self.edges)


def project_property_graph(view: Any, facts: Iterable[Any], entities: dict[str, Any]) -> PropertyGraphProjection:
    """``facts`` are accepted ``KgCandidateFact`` rows in sequence order; ``entities`` by id."""
    facts = list(facts)
    element_of_fact: dict[str, str] = {}
    vertices: dict[str, GraphVertex] = {}
    for fact in (f for f in facts if f.kind == "type"):
        entity = entities[fact.subject_entity_id or ""]
        cls = view.classes[entity.class_id or ""]
        vertices[entity.id] = GraphVertex(
            id=entity.vertex_id,
            label=cls.local_name,
            name=entity.label,
            class_id=cls.id,
            properties={"identifier": entity.identifier, "aliases": list(entity.aliases)},
            fact_ids=[fact.id],
            source_ids=list(fact.document_ids),
        )
        element_of_fact[fact.id] = entity.vertex_id
    for fact in (f for f in facts if f.kind == "attribute"):
        vertex = vertices.get(fact.subject_entity_id or "")
        prop = view.datatype_properties.get(fact.predicate_id or "")
        if vertex is None or prop is None:
            continue
        values = vertex.properties.setdefault(prop.local_name, [])
        if fact.value not in values:
            values.append(fact.value)
        vertex.fact_ids.append(fact.id)
        vertex.source_ids = list(dict.fromkeys([*vertex.source_ids, *fact.document_ids]))
        element_of_fact[fact.id] = vertex.id
    edges: dict[str, GraphEdge] = {}
    skipped = 0
    for fact in (f for f in facts if f.kind == "relationship"):
        subject = vertices.get(fact.subject_entity_id or "")
        obj = vertices.get(fact.object_entity_id or "")
        prop = view.object_properties.get(fact.predicate_id or "")
        if subject is None or obj is None or prop is None:
            skipped += 1
            continue
        identifier = edge_id(subject.id, prop.id, obj.id)
        edge = edges.get(identifier)
        if edge is None:
            edge = edges[identifier] = GraphEdge(
                id=identifier,
                label=prop.local_name,
                predicate_id=prop.id,
                out_id=subject.id,
                in_id=obj.id,
                properties={"predicate_label": prop.label},
            )
        edge.fact_ids.append(fact.id)
        edge.source_ids = list(dict.fromkeys([*edge.source_ids, *fact.document_ids]))
        element_of_fact[fact.id] = identifier
    return PropertyGraphProjection(list(vertices.values()), list(edges.values()), element_of_fact, skipped)


# ---------------------------------------------------------------------------------- RDF


@dataclass
class RdfProjection:
    data_graph: str
    provenance_graph: str
    ontology_graph: str
    data: Graph
    provenance: Graph
    ontology: Graph

    def graphs(self) -> list[tuple[str, Graph]]:
        return [(self.data_graph, self.data), (self.provenance_graph, self.provenance), (self.ontology_graph, self.ontology)]

    @property
    def triple_count(self) -> int:
        return len(self.data) + len(self.provenance) + len(self.ontology)


def build_graph_iris(data_namespace: str, build_id: str) -> tuple[str, str, str]:
    base = f"{data_namespace}build/{build_id}"
    return base, f"{base}/provenance", f"{base}/ontology"


def instance_iri(data_namespace: str, vertex_id: str) -> URIRef:
    return URIRef(f"{data_namespace}e/{vertex_id}")


def relationship_iri(data_namespace: str, identifier: str) -> URIRef:
    return URIRef(f"{data_namespace}r/{identifier}")


def project_rdf(
    projection: PropertyGraphProjection, snapshot: OntologySnapshot, data_namespace: str, build_id: str
) -> RdfProjection:
    snapshot = snapshot.with_iris()
    namespace = snapshot.metadata.namespace
    class_iri = {c.id: URIRef(element_iri(namespace, c)) for c in snapshot.classes}
    object_iri = {p.id: URIRef(element_iri(namespace, p)) for p in snapshot.object_properties}
    attributes = {p.local_name: p for p in snapshot.datatype_properties}
    data_g, provenance_g, ontology_g = build_graph_iris(data_namespace, build_id)
    data = Graph(bind_namespaces="none")
    provenance = Graph(bind_namespaces="none")

    for vertex in sorted(projection.vertices, key=lambda v: v.id):
        node = instance_iri(data_namespace, vertex.id)
        if vertex.class_id in class_iri:
            data.add((node, RDF.type, class_iri[vertex.class_id]))
        data.add((node, RDFS.label, Literal(vertex.name)))
        identifier = vertex.properties.get("identifier")
        if identifier:
            data.add((node, DCTERMS.identifier, Literal(identifier)))
        for alias in vertex.properties.get("aliases") or []:
            data.add((node, SKOS.altLabel, Literal(alias)))
        for key, values in vertex.properties.items():
            prop = attributes.get(key)
            if prop is None:
                continue
            predicate = URIRef(element_iri(namespace, prop))
            for value in values if isinstance(values, list) else [values]:
                if value is None:
                    continue
                datatype = XSD[prop.datatype.value] if prop.semantics.range_declared else XSD.string
                data.add((node, predicate, Literal(str(value), datatype=datatype)))
        for fact_id in vertex.fact_ids:
            provenance.add((node, OLS.fact, Literal(fact_id)))
        for source_id in vertex.source_ids:
            provenance.add((node, OLS.source, Literal(source_id)))

    for edge in sorted(projection.edges, key=lambda e: e.id):
        predicate = object_iri.get(edge.predicate_id)
        if predicate is None:
            continue
        subject, obj = instance_iri(data_namespace, edge.out_id), instance_iri(data_namespace, edge.in_id)
        data.add((subject, predicate, obj))
        resource = relationship_iri(data_namespace, edge.id)
        provenance.add((resource, RDF.type, OLS.Relationship))
        provenance.add((resource, OLS.subject, subject))
        provenance.add((resource, OLS.predicate, predicate))
        provenance.add((resource, OLS.object, obj))
        for fact_id in edge.fact_ids:
            provenance.add((resource, OLS.fact, Literal(fact_id)))
        for source_id in edge.source_ids:
            provenance.add((resource, OLS.source, Literal(source_id)))

    ontology = snapshot_to_owl(snapshot)
    return RdfProjection(data_g, provenance_g, ontology_g, data, provenance, ontology)
