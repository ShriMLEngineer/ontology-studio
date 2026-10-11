"""OLS Semantic Profile -> OWL 2 (RDF) serialisation for snapshot format /2.

The frozen Phase 1-3 serialiser (``registry/rdf.py``) remains in use for legacy (/1) snapshots so
their published artifacts stay reproducible. Differences in /2 (decision D2/D3):

* persisted element IRIs, explicit ontology IRI, custom prefixes and ``owl:imports``;
* ``required`` / ``multi_valued`` are data constraints published as SHACL - they no longer emit
  ``owl:minCardinality`` / ``owl:FunctionalProperty``; OWL characteristics come only from explicit
  semantics;
* preserved extension axioms are merged back verbatim.
"""

from datetime import datetime
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    Restriction,
    default_ontology_iri,
    element_iri,
)
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.semantics.graphs import load_ntriples

CHARACTERISTIC_TYPES = {
    "functional": OWL.FunctionalProperty,
    "inverse_functional": OWL.InverseFunctionalProperty,
    "transitive": OWL.TransitiveProperty,
    "symmetric": OWL.SymmetricProperty,
    "asymmetric": OWL.AsymmetricProperty,
    "reflexive": OWL.ReflexiveProperty,
    "irreflexive": OWL.IrreflexiveProperty,
}
DESCRIPTION_PREDICATES = {"skos:definition": SKOS.definition, "rdfs:comment": RDFS.comment}
STANDARD_PREFIXES = (("owl", OWL), ("rdf", RDF), ("rdfs", RDFS), ("xsd", XSD), ("skos", SKOS), ("dcterms", DCTERMS))
_UNQUALIFIED = {"min": OWL.minCardinality, "max": OWL.maxCardinality, "exact": OWL.cardinality}
_QUALIFIED = {
    "min": OWL.minQualifiedCardinality,
    "max": OWL.maxQualifiedCardinality,
    "exact": OWL.qualifiedCardinality,
}

AnyElement = ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition


def ontology_iri_of(snapshot: OntologySnapshot) -> URIRef:
    return URIRef(snapshot.metadata.ontology_iri or default_ontology_iri(snapshot.metadata.namespace))


def bind_prefixes(graph: Graph, snapshot: OntologySnapshot) -> None:
    for prefix, namespace in STANDARD_PREFIXES:
        graph.bind(prefix, namespace)
    for binding in snapshot.metadata.prefixes:
        graph.bind(binding.prefix, Namespace(binding.namespace), replace=True)
    graph.bind(snapshot.metadata.prefix, Namespace(snapshot.metadata.namespace), replace=True)


def element_iris(snapshot: OntologySnapshot) -> dict[str, URIRef]:
    namespace = snapshot.metadata.namespace
    return {
        e.id: URIRef(element_iri(namespace, e))
        for e in (*snapshot.classes, *snapshot.object_properties, *snapshot.datatype_properties)
    }


def snapshot_to_owl(
    snapshot: OntologySnapshot,
    *,
    version: str | None = None,
    published_at: datetime | None = None,
    release_notes: str = "",
    include_axioms: bool = True,
) -> Graph:
    graph = Graph(bind_namespaces="none")
    bind_prefixes(graph, snapshot)
    metadata = snapshot.metadata
    onto = ontology_iri_of(snapshot)

    graph.add((onto, RDF.type, OWL.Ontology))
    graph.add((onto, RDFS.label, Literal(metadata.name)))
    if metadata.description:
        graph.add((onto, DCTERMS.description, Literal(metadata.description)))
    for imported in metadata.imports:
        graph.add((onto, OWL.imports, URIRef(imported)))
    if version:
        graph.add((onto, OWL.versionInfo, Literal(version)))
        graph.add((onto, OWL.versionIRI, URIRef(f"{onto}/{version}")))
    if published_at:
        graph.add((onto, DCTERMS.issued, Literal(published_at.isoformat(), datatype=XSD.dateTime)))
    if release_notes:
        graph.add((onto, RDFS.comment, Literal(release_notes)))

    iris = element_iris(snapshot)
    properties: dict[str, AnyElement] = {p.id: p for p in (*snapshot.object_properties, *snapshot.datatype_properties)}

    def ref(element_id: str | None) -> URIRef | None:
        return iris.get(element_id) if element_id else None

    def annotate(iri: URIRef, element: AnyElement) -> None:
        semantics = element.semantics
        lang = semantics.annotation_language
        graph.add((iri, RDFS.label, Literal(element.label, lang=lang)))
        graph.add((iri, DCTERMS.identifier, Literal(element.id)))
        if element.description:
            predicate = DESCRIPTION_PREDICATES[semantics.description_predicate]
            graph.add((iri, predicate, Literal(element.description, lang=lang)))
        for alias in element.aliases:
            graph.add((iri, SKOS.altLabel, Literal(alias, lang=lang)))
        graph.add((iri, RDFS.isDefinedBy, onto))
        if semantics.deprecated:
            graph.add((iri, OWL.deprecated, Literal(True)))

    for cls in snapshot.classes:
        iri = iris[cls.id]
        graph.add((iri, RDF.type, OWL.Class))
        annotate(iri, cls)
        for parent in cls.parent_ids:
            if (target := ref(parent)) is not None:
                graph.add((iri, RDFS.subClassOf, target))
        for other in cls.semantics.equivalent_ids:
            if (target := ref(other)) is not None:
                graph.add((iri, OWL.equivalentClass, target))
        for other in cls.semantics.disjoint_ids:
            if (target := ref(other)) is not None:
                graph.add((iri, OWL.disjointWith, target))
        for restriction in cls.semantics.restrictions:
            node = restriction_node(graph, restriction, iris, properties)
            if node is not None:
                graph.add((iri, RDFS.subClassOf, node))

    for prop in snapshot.object_properties:
        iri = iris[prop.id]
        graph.add((iri, RDF.type, OWL.ObjectProperty))
        annotate(iri, prop)
        if (domain := ref(prop.domain_id)) is not None:
            graph.add((iri, RDFS.domain, domain))
        if (range_ := ref(prop.range_id)) is not None:
            graph.add((iri, RDFS.range, range_))
        semantics = prop.semantics
        for parent in semantics.parent_ids:
            if (target := ref(parent)) is not None:
                graph.add((iri, RDFS.subPropertyOf, target))
        if (inverse := ref(semantics.inverse_id)) is not None:
            graph.add((iri, OWL.inverseOf, inverse))
        for characteristic in semantics.characteristics:
            graph.add((iri, RDF.type, CHARACTERISTIC_TYPES[characteristic]))
        for other in semantics.equivalent_ids:
            if (target := ref(other)) is not None:
                graph.add((iri, OWL.equivalentProperty, target))

    for prop in snapshot.datatype_properties:
        iri = iris[prop.id]
        graph.add((iri, RDF.type, OWL.DatatypeProperty))
        annotate(iri, prop)
        semantics = prop.semantics
        if semantics.range_declared:
            graph.add((iri, RDFS.range, XSD[prop.datatype.value]))
        if semantics.functional:
            graph.add((iri, RDF.type, OWL.FunctionalProperty))
        if (domain := ref(prop.domain_id)) is not None:
            graph.add((iri, RDFS.domain, domain))
        for parent in semantics.parent_ids:
            if (target := ref(parent)) is not None:
                graph.add((iri, RDFS.subPropertyOf, target))
        for other in semantics.equivalent_ids:
            if (target := ref(other)) is not None:
                graph.add((iri, OWL.equivalentProperty, target))

    if include_axioms:
        for axiom in snapshot.extension_axioms:
            if axiom.scope == "ontology":
                load_ntriples(graph, axiom.ntriples)
    return graph


def restriction_node(
    graph: Graph, restriction: Restriction, iris: dict[str, URIRef], properties: dict[str, Any]
) -> BNode | None:
    prop = properties.get(restriction.property_id)
    if prop is None:
        return None
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, iris[prop.id]))
    filler: URIRef | None = None
    if restriction.class_id:
        filler = iris.get(restriction.class_id)
        if filler is None:
            graph.remove((node, None, None))
            return None
    elif restriction.datatype:
        filler = XSD[restriction.datatype.value]

    if restriction.kind in ("some", "all"):
        predicate = OWL.someValuesFrom if restriction.kind == "some" else OWL.allValuesFrom
        graph.add((node, predicate, filler))  # type: ignore[arg-type]
    elif restriction.kind == "has_value":
        if isinstance(prop, ObjectPropertyDefinition):
            graph.add((node, OWL.hasValue, URIRef(str(restriction.value))))
        else:
            graph.add((node, OWL.hasValue, Literal(restriction.value, datatype=XSD[prop.datatype.value])))
    else:
        count = Literal(restriction.cardinality, datatype=XSD.nonNegativeInteger)
        if filler is None:
            graph.add((node, _UNQUALIFIED[restriction.kind], count))
        else:
            graph.add((node, _QUALIFIED[restriction.kind], count))
            on = OWL.onClass if restriction.class_id else OWL.onDataRange
            graph.add((node, on, filler))
    return node
