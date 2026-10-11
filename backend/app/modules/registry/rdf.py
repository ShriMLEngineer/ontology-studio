"""OWL / Turtle serialisation of canonical ontology snapshots with RDFLib."""

from datetime import datetime

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from app.modules.registry.snapshot import OntologySnapshot


def ontology_iri(namespace: str) -> URIRef:
    return URIRef(namespace.rstrip("#/:"))


def snapshot_to_graph(
    snapshot: OntologySnapshot,
    *,
    version: str | None = None,
    published_at: datetime | None = None,
    release_notes: str = "",
) -> Graph:
    metadata = snapshot.metadata
    ns = Namespace(metadata.namespace)
    graph = Graph()
    graph.bind(metadata.prefix, ns)
    for prefix, namespace in (("owl", OWL), ("rdfs", RDFS), ("xsd", XSD), ("skos", SKOS), ("dcterms", DCTERMS)):
        graph.bind(prefix, namespace)

    onto = ontology_iri(metadata.namespace)
    graph.add((onto, RDF.type, OWL.Ontology))
    graph.add((onto, RDFS.label, Literal(metadata.name)))
    if metadata.description:
        graph.add((onto, DCTERMS.description, Literal(metadata.description)))
    if version:
        graph.add((onto, OWL.versionInfo, Literal(version)))
        graph.add((onto, OWL.versionIRI, URIRef(f"{onto}/{version}")))
    if published_at:
        graph.add((onto, DCTERMS.issued, Literal(published_at.isoformat(), datatype=XSD.dateTime)))
    if release_notes:
        graph.add((onto, RDFS.comment, Literal(release_notes)))

    iris = {
        e.id: ns[e.local_name]
        for e in (*snapshot.classes, *snapshot.object_properties, *snapshot.datatype_properties)
    }

    def annotate(iri: URIRef, element: object) -> None:
        graph.add((iri, RDFS.label, Literal(element.label)))  # type: ignore[attr-defined]
        graph.add((iri, DCTERMS.identifier, Literal(element.id)))  # type: ignore[attr-defined]
        if element.description:  # type: ignore[attr-defined]
            graph.add((iri, SKOS.definition, Literal(element.description)))  # type: ignore[attr-defined]
        for alias in element.aliases:  # type: ignore[attr-defined]
            graph.add((iri, SKOS.altLabel, Literal(alias)))
        graph.add((iri, RDFS.isDefinedBy, onto))

    for cls in snapshot.classes:
        iri = iris[cls.id]
        graph.add((iri, RDF.type, OWL.Class))
        annotate(iri, cls)
        for parent in cls.parent_ids:
            graph.add((iri, RDFS.subClassOf, iris[parent]))

    for prop in snapshot.object_properties:
        iri = iris[prop.id]
        graph.add((iri, RDF.type, OWL.ObjectProperty))
        annotate(iri, prop)
        if prop.domain_id:
            graph.add((iri, RDFS.domain, iris[prop.domain_id]))
        if prop.range_id:
            graph.add((iri, RDFS.range, iris[prop.range_id]))

    for prop in snapshot.datatype_properties:
        iri = iris[prop.id]
        graph.add((iri, RDF.type, OWL.DatatypeProperty))
        annotate(iri, prop)
        graph.add((iri, RDFS.range, XSD[prop.datatype.value]))
        if not prop.multi_valued:
            graph.add((iri, RDF.type, OWL.FunctionalProperty))
        if prop.domain_id:
            domain = iris[prop.domain_id]
            graph.add((iri, RDFS.domain, domain))
            if prop.required:
                restriction = BNode()
                graph.add((restriction, RDF.type, OWL.Restriction))
                graph.add((restriction, OWL.onProperty, iri))
                graph.add((restriction, OWL.minCardinality, Literal(1, datatype=XSD.nonNegativeInteger)))
                graph.add((domain, RDFS.subClassOf, restriction))
    return graph


def to_turtle(snapshot: OntologySnapshot, **kwargs: object) -> bytes:
    return snapshot_to_graph(snapshot, **kwargs).serialize(format="turtle").encode("utf-8")  # type: ignore[arg-type]
