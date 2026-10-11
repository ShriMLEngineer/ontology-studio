"""RDF graph utilities shared by the serialiser, importer, reasoner and validators."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from rdflib import BNode, Graph
from rdflib.compare import to_canonical_graph
from rdflib.term import Node

from app.core.errors import BusinessRuleError

RdfFormat = Literal["turtle", "rdfxml", "jsonld", "ntriples"]
Triple = tuple[Node, Node, Node]


@dataclass(frozen=True)
class FormatInfo:
    rdflib_name: str
    media_type: str
    extension: str


FORMATS: dict[str, FormatInfo] = {
    "turtle": FormatInfo("turtle", "text/turtle", "ttl"),
    "rdfxml": FormatInfo("xml", "application/rdf+xml", "rdf"),
    "jsonld": FormatInfo("json-ld", "application/ld+json", "jsonld"),
    "ntriples": FormatInfo("nt", "application/n-triples", "nt"),
}

_EXTENSIONS = {
    "ttl": "turtle",
    "turtle": "turtle",
    "rdf": "rdfxml",
    "owl": "rdfxml",
    "xml": "rdfxml",
    "jsonld": "jsonld",
    "json": "jsonld",
    "nt": "ntriples",
}


class RdfParseError(BusinessRuleError):
    code = "RDF_PARSE_ERROR"


def detect_format(filename: str | None, declared: str | None = None) -> str:
    if declared:
        if declared not in FORMATS:
            raise RdfParseError(f"Unsupported RDF format '{declared}'. Use one of: {', '.join(FORMATS)}.")
        return declared
    extension = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if extension in _EXTENSIONS:
        return _EXTENSIONS[extension]
    raise RdfParseError(
        "Cannot determine the RDF format from the file name. Choose the format explicitly "
        f"({', '.join(FORMATS)})."
    )


def parse_rdf(data: bytes, rdf_format: str) -> Graph:
    """Parse ``data``; only prefixes declared in the document are bound on the result."""
    graph = Graph(bind_namespaces="none")
    try:
        graph.parse(data=data.decode("utf-8-sig"), format=FORMATS[rdf_format].rdflib_name)
    except UnicodeDecodeError as exc:
        raise RdfParseError("The RDF document is not valid UTF-8.") from exc
    except Exception as exc:  # noqa: BLE001 - rdflib raises many parser-specific exception types
        raise RdfParseError(f"The RDF document could not be parsed as {rdf_format}: {exc}") from exc
    return graph


def serialize(graph: Graph, rdf_format: str) -> bytes:
    text = graph.serialize(format=FORMATS[rdf_format].rdflib_name)
    return text.encode("utf-8") if isinstance(text, str) else text


def has_bnode(triple: Triple) -> bool:
    return isinstance(triple[0], BNode) or isinstance(triple[2], BNode)


def bnode_components(triples: Iterable[Triple]) -> list[list[Triple]]:
    """Group triples into blank-node closures; ground triples form singleton components.

    A component contains every triple reachable through shared blank nodes, so it can be preserved
    or compared as a unit without dangling blank nodes.
    """
    triples = list(triples)
    parent: dict[Node, Node] = {}

    def find(node: Node) -> Node:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for s, _, o in triples:
        if isinstance(s, BNode) and isinstance(o, BNode):
            parent[find(s)] = find(o)
    groups: dict[Node, list[Triple]] = defaultdict(list)
    ground: list[list[Triple]] = []
    for triple in triples:
        s, _, o = triple
        anchor = s if isinstance(s, BNode) else o if isinstance(o, BNode) else None
        if anchor is None:
            ground.append([triple])
        else:
            groups[find(anchor)].append(triple)
    return ground + list(groups.values())


def to_ntriples(triples: Iterable[Triple]) -> str:
    graph = Graph(bind_namespaces="none")
    for triple in triples:
        graph.add(triple)
    lines = graph.serialize(format="nt").splitlines()
    return "\n".join(sorted(line for line in lines if line.strip())) + "\n"


def canonical_component(triples: list[Triple]) -> str:
    """Isomorphism-invariant N-Triples text (blank nodes canonically relabelled, lines sorted)."""
    graph = Graph(bind_namespaces="none")
    for triple in triples:
        graph.add(triple)
    if any(has_bnode(t) for t in triples):
        graph = to_canonical_graph(graph)
    lines = graph.serialize(format="nt").splitlines()
    return "\n".join(sorted(line for line in lines if line.strip()))


def canonical_ntriples(ntriples: str) -> str:
    graph = Graph(bind_namespaces="none")
    graph.parse(data=ntriples, format="nt")
    return canonical_component(list(graph))


def load_ntriples(graph: Graph, ntriples: str) -> None:
    """Add preserved triples to ``graph`` with fresh blank nodes (no accidental blank-node merging)."""
    temp = Graph(bind_namespaces="none")
    temp.parse(data=ntriples, format="nt")
    for triple in temp:
        graph.add(triple)
