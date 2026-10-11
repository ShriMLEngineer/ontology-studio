"""OWL 2 RL entailment preview with owlrl (decision D11: informational only).

Entailments are computed on a copy of the ontology graph and never written back to the draft, a
published version or a graph target. owlrl inconsistency findings are reported separately from
structural validation, SHACL validation and evidence validation.
"""

import time

from owlrl import OWLRL_Semantics
from pydantic import BaseModel, Field
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from app.modules.semantics.owl import CHARACTERISTIC_TYPES

_BUILTIN = tuple(str(ns) for ns in (RDF, RDFS, OWL, XSD))
_INTERESTING = {
    RDFS.subClassOf: "subclass",
    OWL.equivalentClass: "equivalence",
    RDFS.subPropertyOf: "subproperty",
    OWL.equivalentProperty: "equivalence",
    RDFS.domain: "domain",
    RDFS.range: "range",
    OWL.inverseOf: "inverse",
    OWL.disjointWith: "disjointness",
    RDF.type: "type",
    OWL.sameAs: "identity",
}
_CHARACTERISTICS = set(CHARACTERISTIC_TYPES.values())
MAX_ENTAILMENTS = 2000


class Entailment(BaseModel):
    category: str
    subject: str
    predicate: str
    object: str
    display: str


class EntailmentReport(BaseModel):
    engine: str = "owlrl (OWL 2 RL forward chaining)"
    informational: bool = Field(
        default=True, description="Entailments are a preview; they never change the ontology or the knowledge graph"
    )
    asserted_triples: int
    inferred_triples: int
    entailments: list[Entailment]
    by_category: dict[str, int]
    inconsistencies: list[str]
    truncated: bool
    duration_ms: int


def _builtin(term: object) -> bool:
    return isinstance(term, URIRef) and str(term).startswith(_BUILTIN)


def _relevant(s: object, p: object, o: object) -> bool:
    if p not in _INTERESTING or not isinstance(s, URIRef) or _builtin(s) or s == o:
        return False
    if isinstance(o, (BNode, Literal)):
        return False
    if p == RDF.type:
        return not _builtin(o) or o in _CHARACTERISTICS
    return not _builtin(o)


def entailment_preview(graph: Graph) -> EntailmentReport:
    started = time.perf_counter()
    working = Graph(bind_namespaces="none")
    for triple in graph:
        working.add(triple)
    for prefix, namespace in graph.namespaces():
        working.bind(prefix, namespace)
    closure = OWLRL_Semantics(working, False, False, rdfs=False)
    closure.closure()

    manager = graph.namespace_manager
    inferred = [t for t in working if t not in graph]
    relevant = sorted((t for t in inferred if _relevant(*t)), key=lambda t: (str(t[1]), str(t[0]), str(t[2])))
    entailments = [
        Entailment(
            category=_INTERESTING[p],
            subject=str(s),
            predicate=str(p),
            object=str(o),
            display=f"{s.n3(manager)} {p.n3(manager)} {o.n3(manager)}",
        )
        for s, p, o in relevant[:MAX_ENTAILMENTS]
    ]
    by_category: dict[str, int] = {}
    for s, p, o in relevant:
        by_category[_INTERESTING[p]] = by_category.get(_INTERESTING[p], 0) + 1
    return EntailmentReport(
        asserted_triples=len(graph),
        inferred_triples=len(inferred),
        entailments=entailments,
        by_category=dict(sorted(by_category.items())),
        inconsistencies=[str(m) for m in closure.error_messages],
        truncated=len(relevant) > MAX_ENTAILMENTS,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
