"""Rebuild the property-graph view of a build from its RDF projection read back from a target.

Inverse of :func:`app.modules.graph.projection.project_rdf`: instance IRIs give vertex ids,
``rdf:type`` the class, relationship resources in the provenance graph the edge ids, and
``ols:fact``/``ols:source`` the provenance. Triples the reader cannot attribute (for example data
added to the target outside this application) are counted, never invented into elements.
"""

from dataclasses import dataclass, field

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS

from app.modules.graph.memory_store import MemoryGraphStore
from app.modules.graph.projection import OLS
from app.modules.graph.store import GraphEdge, GraphVertex
from app.modules.ontology.domain import element_iri
from app.modules.registry.snapshot import OntologySnapshot


@dataclass
class ReadStats:
    vertices: int = 0
    edges: int = 0
    untyped_resources: int = 0
    relationships_missing_in_data: int = 0
    warnings: list[str] = field(default_factory=list)


def read_rdf_projection(
    data: Graph,
    provenance: Graph,
    snapshot: OntologySnapshot,
    data_namespace: str,
    *,
    name: str,
    graph_id: str,
) -> tuple[MemoryGraphStore, ReadStats]:
    snapshot = snapshot.with_iris()
    namespace = snapshot.metadata.namespace
    classes = {element_iri(namespace, c): c for c in snapshot.classes}
    objects = {element_iri(namespace, p): p for p in snapshot.object_properties}
    attributes = {element_iri(namespace, p): p for p in snapshot.datatype_properties}
    entity_prefix, relationship_prefix = f"{data_namespace}e/", f"{data_namespace}r/"
    stats = ReadStats()

    vertices: list[GraphVertex] = []
    for subject in sorted({s for s in data.subjects() if isinstance(s, URIRef)}, key=str):
        iri = str(subject)
        if not iri.startswith(entity_prefix):
            continue
        cls = next((classes[str(o)] for o in data.objects(subject, RDF.type) if str(o) in classes), None)
        if cls is None:
            stats.untyped_resources += 1
            continue
        identifier = data.value(subject, DCTERMS.identifier)
        properties: dict[str, object] = {
            "identifier": str(identifier) if identifier is not None else None,
            "aliases": sorted(str(o) for o in data.objects(subject, SKOS.altLabel)),
        }
        for predicate, value in data.predicate_objects(subject):
            prop = attributes.get(str(predicate))
            if prop is not None and isinstance(value, Literal):
                values = properties.setdefault(prop.local_name, [])
                assert isinstance(values, list)
                values.append(str(value))
        for key, values in properties.items():
            if key not in ("identifier", "aliases") and isinstance(values, list):
                values.sort()
        vertices.append(
            GraphVertex(
                id=iri[len(entity_prefix):],
                label=cls.local_name,
                name=str(data.value(subject, RDFS.label) or ""),
                class_id=cls.id,
                properties=properties,
                fact_ids=sorted(str(o) for o in provenance.objects(subject, OLS.fact)),
                source_ids=sorted(str(o) for o in provenance.objects(subject, OLS.source)),
            )
        )
    known = {v.id for v in vertices}

    edges: list[GraphEdge] = []
    for resource in sorted(provenance.subjects(RDF.type, OLS.Relationship), key=str):
        iri = str(resource)
        if not iri.startswith(relationship_prefix):
            continue
        subject, predicate, obj = (provenance.value(resource, p) for p in (OLS.subject, OLS.predicate, OLS.object))
        prop = objects.get(str(predicate)) if predicate is not None else None
        if subject is None or obj is None or prop is None or (subject, predicate, obj) not in data:
            stats.relationships_missing_in_data += 1
            continue
        out_id, in_id = str(subject)[len(entity_prefix):], str(obj)[len(entity_prefix):]
        if out_id not in known or in_id not in known:
            stats.relationships_missing_in_data += 1
            continue
        edges.append(
            GraphEdge(
                id=iri[len(relationship_prefix):],
                label=prop.local_name,
                predicate_id=prop.id,
                out_id=out_id,
                in_id=in_id,
                properties={"predicate_label": prop.label},
                fact_ids=sorted(str(o) for o in provenance.objects(resource, OLS.fact)),
                source_ids=sorted(str(o) for o in provenance.objects(resource, OLS.source)),
            )
        )
    stats.vertices, stats.edges = len(vertices), len(edges)
    if stats.untyped_resources:
        stats.warnings.append(f"{stats.untyped_resources} instance resource(s) without a class of the ontology were skipped.")
    if stats.relationships_missing_in_data:
        stats.warnings.append(
            f"{stats.relationships_missing_in_data} relationship(s) recorded in the provenance graph are missing from the data graph."
        )
    return MemoryGraphStore(name, graph_id, vertices, edges), stats
