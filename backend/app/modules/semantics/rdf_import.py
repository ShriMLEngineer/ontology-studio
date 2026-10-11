"""RDF / OWL import into the OLS Semantic Profile without silent semantic loss (decision D1, D10).

Algorithm
1. Parse the document (Turtle, RDF/XML, JSON-LD or N-Triples).
2. Interpret profile patterns conservatively (declared classes and properties, labels, definitions,
   hierarchy, single domain/range, characteristics, equivalence, disjointness, supported
   restrictions, deprecation). Anything ambiguous is *not* interpreted.
3. Re-serialise the typed model and reconcile it with the source by blank-node component: every
   source component that the typed model does not reproduce exactly becomes a preserved
   :class:`ExtensionAxiom` (shapes go to the ``shapes`` scope).
4. Verify that the final export (typed model + preserved axioms) contains every source triple except
   the documented *superseded* version header triples, and report documented bookkeeping additions.
"""

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SH, SKOS, XSD

from app.core.errors import BusinessRuleError
from app.core.ids import new_element_id
from app.modules.ontology.domain import (
    ELEMENT_ID_PATTERN,
    ClassDefinition,
    ClassSemantics,
    DatatypePropertyDefinition,
    DatatypePropertySemantics,
    ExtensionAxiom,
    ObjectPropertyDefinition,
    ObjectPropertySemantics,
    OntologySchema,
    PrefixBinding,
    Restriction,
    XsdDatatype,
)
from app.modules.registry.snapshot import OntologySnapshot, SnapshotMetadata
from app.modules.semantics.graphs import (
    Triple,
    bnode_components,
    canonical_component,
    has_bnode,
    load_ntriples,
    to_ntriples,
)
from app.modules.semantics.owl import CHARACTERISTIC_TYPES, STANDARD_PREFIXES, ontology_iri_of, snapshot_to_owl

_ELEMENT_ID = re.compile(ELEMENT_ID_PATTERN)
_LOCAL_NAME_INVALID = re.compile(r"[^A-Za-z0-9_\-]")
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
_RESERVED_PREFIXES = {"rdf", "rdfs", "owl", "xsd", "xml", "sh"}
_BUILTIN_NAMESPACES = tuple(str(ns) for ns in (RDF, RDFS, OWL, XSD))
_SUPERSEDED_HEADER = (OWL.versionInfo, OWL.versionIRI, DCTERMS.issued)
_BOOKKEEPING = {DCTERMS.identifier, RDFS.isDefinedBy}
_ANNOTATION_PREDICATES = {
    RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy, OWL.deprecated, OWL.versionInfo,
    SKOS.definition, SKOS.altLabel, SKOS.prefLabel, SKOS.hiddenLabel, SKOS.note, SKOS.example,
    SKOS.scopeNote, SKOS.editorialNote, SKOS.historyNote, SKOS.changeNote,
}
_CLASS_EXPRESSION = {OWL.unionOf, OWL.intersectionOf, OWL.complementOf, OWL.oneOf}
_NARY = {OWL.AllDisjointClasses, OWL.AllDifferent, OWL.AllDisjointProperties, OWL.NegativePropertyAssertion}
_XSD_TYPES = {XSD[d.value]: d for d in XsdDatatype}
_CARDINALITY = {
    OWL.minCardinality: ("min", False), OWL.maxCardinality: ("max", False), OWL.cardinality: ("exact", False),
    OWL.minQualifiedCardinality: ("min", True), OWL.maxQualifiedCardinality: ("max", True),
    OWL.qualifiedCardinality: ("exact", True),
}
_CHARACTERISTIC_BY_TYPE = {v: k for k, v in CHARACTERISTIC_TYPES.items()}
MAX_REPORTED_TRIPLES = 200


class ImportReport(BaseModel):
    rdf_format: str
    source_triples: int
    consumed_triples: int
    preserved_triples: int
    superseded_triples: int
    added_triples: int
    classes: int
    object_properties: int
    datatype_properties: int
    preserved_axioms: int
    preserved_by_kind: dict[str, int] = Field(default_factory=dict)
    superseded: list[str] = Field(default_factory=list, description="N-Triples lines replaced at publication")
    added: list[str] = Field(default_factory=list, description="Documented bookkeeping triples added on export")
    warnings: list[str] = Field(default_factory=list)
    lossless: bool = Field(description="Every source triple except superseded ones is present in the export")


class ImportResult(BaseModel):
    metadata: SnapshotMetadata
    schema_: OntologySchema = Field(alias="schema")
    report: ImportReport

    model_config = {"populate_by_name": True}


def _split(iri: str) -> tuple[str, str]:
    cut = max(iri.rfind("#"), iri.rfind("/"))
    return (iri[: cut + 1], iri[cut + 1 :]) if cut >= 0 else (iri, "")


def _humanize(local: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local).replace("_", " ").replace("-", " ").strip()
    return (spaced[:1].upper() + spaced[1:])[:200] if spaced else "Unnamed"


class _Importer:
    def __init__(self, graph: Graph, rdf_format: str) -> None:
        self.graph = graph
        self.rdf_format = rdf_format
        self.warnings: list[str] = []

    # -------------------------------------------------------------------------- helpers

    def declared(self, rdf_type: URIRef) -> list[URIRef]:
        return sorted(
            {
                s
                for s in self.graph.subjects(RDF.type, rdf_type)
                if isinstance(s, URIRef) and not str(s).startswith(_BUILTIN_NAMESPACES)
            },
            key=str,
        )

    def uris(self, subject: URIRef, predicate: URIRef) -> list[URIRef]:
        return sorted((o for o in self.graph.objects(subject, predicate) if isinstance(o, URIRef)), key=str)

    def single(self, subject: URIRef, predicate: URIRef, allowed: dict[URIRef, Any]) -> Any:
        values = list(self.graph.objects(subject, predicate))
        if len(values) == 1 and isinstance(values[0], URIRef) and values[0] in allowed:
            return allowed[values[0]]
        return None

    def plain_literals(self, subject: URIRef, predicate: URIRef, lang: str | None, max_length: int) -> list[str]:
        values = []
        for o in self.graph.objects(subject, predicate):
            if not isinstance(o, Literal) or o.datatype is not None or o.language != lang:
                continue
            text = str(o)
            if text and text == text.strip() and len(text) <= max_length:
                values.append(text)
        return sorted(values)

    def language_of(self, subject: URIRef) -> str | None:
        langs: list[str | None] = []
        for predicate in (RDFS.label, SKOS.definition, RDFS.comment, SKOS.altLabel):
            langs += [
                o.language for o in self.graph.objects(subject, predicate)
                if isinstance(o, Literal) and o.datatype is None
            ]
            if langs:
                break
        if not langs or None in langs:
            return None
        lowered = sorted({lang for lang in langs if lang})
        return next((lang for lang in lowered if lang.lower() == "en"), lowered[0])

    # -------------------------------------------------------------------------- interpretation

    def run(self, *, name: str | None, namespace: str | None, prefix: str | None, filename: str | None) -> ImportResult:
        headers = self.declared(OWL.Ontology)
        onto = headers[0] if headers else None
        if len(headers) > 1:
            self.warnings.append(
                f"The document declares {len(headers)} ontologies; <{onto}> is used as the header, the other "
                "headers are preserved as extension axioms."
            )

        class_iris = self.declared(OWL.Class)
        rdfs_only = [c for c in self.declared(RDFS.Class) if c not in set(class_iris)]
        if rdfs_only:
            self.warnings.append(
                f"{len(rdfs_only)} rdfs:Class declaration(s) are imported as owl:Class; the original "
                "rdfs:Class typing is preserved."
            )
        class_iris = sorted({*class_iris, *rdfs_only}, key=str)
        class_set = set(class_iris)
        object_iris = [p for p in self.declared(OWL.ObjectProperty) if p not in class_set]
        datatype_iris = [
            p for p in self.declared(OWL.DatatypeProperty) if p not in class_set and p not in set(object_iris)
        ]
        punned = set(self.declared(OWL.ObjectProperty)) & set(self.declared(OWL.DatatypeProperty))
        if punned:
            self.warnings.append(
                f"{len(punned)} propert(y/ies) declared as both object and datatype property are imported as "
                "object properties; the datatype declaration is preserved."
            )

        entity_iris = [*class_iris, *object_iris, *datatype_iris]
        namespace = (namespace or "").strip() or self._namespace(entity_iris, onto)
        prefix = (prefix or "").strip() or self._prefix(namespace)
        prefixes = self._prefixes(namespace, prefix)

        ids = self._assign_ids(entity_iris)
        local_names = self._local_names(entity_iris, namespace)
        class_ids = {iri: ids[iri] for iri in class_iris}
        object_ids = {iri: ids[iri] for iri in object_iris}
        datatype_ids = {iri: ids[iri] for iri in datatype_iris}
        datatypes: dict[URIRef, XsdDatatype | None] = {
            iri: self.single(iri, RDFS.range, _XSD_TYPES) for iri in datatype_iris
        }
        unsupported = [iri for iri, dt in datatypes.items() if dt is None and list(self.graph.objects(iri, RDFS.range))]
        if unsupported:
            self.warnings.append(
                f"{len(unsupported)} datatype propert(y/ies) declare a range outside the supported XSD datatypes "
                "(or several ranges); values are handled as strings and the original rdfs:range is preserved."
            )
        self.class_iris = class_set

        try:
            classes = [
                self._class(iri, ids[iri], local_names[iri], class_ids, object_ids, datatype_ids, datatypes)
                for iri in class_iris
            ]
            object_properties = [
                self._object_property(iri, ids[iri], local_names[iri], class_ids, object_ids) for iri in object_iris
            ]
            datatype_properties = [
                self._datatype_property(iri, ids[iri], local_names[iri], class_ids, datatype_ids, datatypes[iri])
                for iri in datatype_iris
            ]
        except PydanticValidationError as exc:  # pragma: no cover - interpretation guards prevent this
            raise BusinessRuleError(
                "The RDF document contains an element the importer could not represent.",
                code="RDF_IMPORT_FAILED",
                details={"errors": exc.errors(include_url=False, include_context=False)},
            ) from exc

        header_label = self.plain_literals(onto, RDFS.label, None, 200) if onto is not None else []
        header_description = self.plain_literals(onto, DCTERMS.description, None, 4000) if onto is not None else []
        open_signatures = sum(
            1 for p in [*object_properties, *datatype_properties] if p.domain_id is None
        ) + sum(1 for p in object_properties if p.range_id is None)
        if open_signatures:
            self.warnings.append(
                f"{open_signatures} domain/range declaration(s) are absent or not a single declared class; missing "
                "domains and ranges are reported as warnings (require_domain_range = false)."
            )
        if not name:
            name = header_label[0] if header_label else (filename.rsplit(".", 1)[0] if filename else _split(namespace)[1])
        metadata = SnapshotMetadata(
            name=(name or "Imported ontology").strip()[:200],
            namespace=namespace,
            prefix=prefix,
            description=header_description[0] if header_description else "",
            ontology_iri=str(onto) if onto is not None else None,
            prefixes=prefixes,
            imports=[str(i) for i in self.uris(onto, OWL.imports)] if onto is not None else [],
            require_domain_range=not open_signatures,
        )
        typed = OntologySnapshot(
            metadata=metadata,
            classes=classes,
            object_properties=object_properties,
            datatype_properties=datatype_properties,
        )
        return self._reconcile(typed, onto, ids)

    def _namespace(self, entity_iris: list[URIRef], onto: URIRef | None) -> str:
        counts = Counter(_split(str(iri))[0] for iri in entity_iris)
        if counts:
            return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if onto is not None:
            text = str(onto)
            return text if text.endswith(("#", "/")) else f"{text}#"
        raise BusinessRuleError(
            "The document declares no ontology, classes or properties. Provide a namespace to import it.",
            code="IMPORT_NAMESPACE_REQUIRED",
        )

    def _prefix(self, namespace: str) -> str:
        for bound, ns in self.graph.namespaces():
            if str(ns) == namespace and _PREFIX_RE.match(bound or "") and bound not in _RESERVED_PREFIXES:
                return bound
        segment = re.sub(r"[^A-Za-z0-9_\-]", "", _split(namespace.rstrip("#/"))[1])
        segment = segment.lstrip("0123456789_-")[:40]
        return segment.lower() if segment and segment.lower() not in _RESERVED_PREFIXES else "ont"

    def _prefixes(self, namespace: str, prefix: str) -> list[PrefixBinding]:
        standard = {p: str(ns) for p, ns in STANDARD_PREFIXES} | {"xml": "http://www.w3.org/XML/1998/namespace"}
        bindings = []
        for bound, ns in sorted(self.graph.namespaces(), key=lambda kv: kv[0]):
            ns_text = str(ns)
            if ns_text == namespace or bound == prefix or standard.get(bound) == ns_text:
                continue
            try:
                bindings.append(PrefixBinding(prefix=bound, namespace=ns_text))
            except PydanticValidationError:
                self.warnings.append(f"Prefix '{bound}' is not a valid prefix name and was not kept.")
        return bindings

    def _assign_ids(self, entity_iris: list[URIRef]) -> dict[URIRef, str]:
        ids: dict[URIRef, str] = {}
        used: set[str] = set()
        kinds = {RDFS.Class: "cls", OWL.Class: "cls", OWL.ObjectProperty: "op", OWL.DatatypeProperty: "dp"}
        for iri in entity_iris:
            candidates = sorted(
                str(o) for o in self.graph.objects(iri, DCTERMS.identifier)
                if isinstance(o, Literal) and o.datatype is None and o.language is None
            )
            chosen = next((c for c in candidates if _ELEMENT_ID.match(c) and c not in used), None)
            if chosen is None:
                types = set(self.graph.objects(iri, RDF.type))
                kind = next((k for t, k in kinds.items() if t in types), "el")
                chosen = new_element_id(kind)
            used.add(chosen)
            ids[iri] = chosen
        return ids

    def _local_names(self, entity_iris: list[URIRef], namespace: str) -> dict[URIRef, str]:
        names: dict[URIRef, str] = {}
        used: set[str] = set()
        for iri in entity_iris:
            text = str(iri)
            local = text[len(namespace):] if text.startswith(namespace) else _split(text)[1]
            local = _LOCAL_NAME_INVALID.sub("_", local)[:180] or "unnamed"
            if not re.match(r"^[A-Za-z_]", local):
                local = f"_{local}"
            candidate, n = local, 2
            while candidate.casefold() in used:
                candidate, n = f"{local}_{n}", n + 1
            used.add(candidate.casefold())
            names[iri] = candidate
        return names

    def _annotations(self, iri: URIRef, local_name: str) -> dict[str, Any]:
        lang = self.language_of(iri)
        labels = self.plain_literals(iri, RDFS.label, lang, 200)
        definitions = self.plain_literals(iri, SKOS.definition, lang, 4000)
        comments = self.plain_literals(iri, RDFS.comment, lang, 4000)
        predicate, description = ("skos:definition", definitions[0]) if definitions else (
            ("rdfs:comment", comments[0]) if comments else ("skos:definition", "")
        )
        aliases: list[str] = []
        seen: set[str] = set()
        for alias in self.plain_literals(iri, SKOS.altLabel, lang, 200):
            if alias.casefold() not in seen and len(aliases) < 50:
                seen.add(alias.casefold())
                aliases.append(alias)
        return {
            "label": labels[0] if labels else _humanize(local_name),
            "description": description,
            "aliases": aliases,
            "semantics": {
                "annotation_language": lang,
                "description_predicate": predicate,
                "deprecated": (iri, OWL.deprecated, Literal(True)) in self.graph,
            },
        }

    def _class(
        self,
        iri: URIRef,
        element_id: str,
        local_name: str,
        class_ids: dict[URIRef, str],
        object_ids: dict[URIRef, str],
        datatype_ids: dict[URIRef, str],
        datatypes: dict[URIRef, XsdDatatype | None],
    ) -> ClassDefinition:
        base = self._annotations(iri, local_name)
        parents = [class_ids[p] for p in self.uris(iri, RDFS.subClassOf) if p in class_ids and p != iri][:20]
        restrictions = []
        for node in sorted((o for o in self.graph.objects(iri, RDFS.subClassOf) if isinstance(o, BNode)), key=str):
            restriction = self._restriction(node, class_ids, object_ids, datatype_ids, datatypes)
            if restriction is not None and len(restrictions) < 100:
                restrictions.append(restriction)
        semantics = ClassSemantics(
            **base.pop("semantics"),
            equivalent_ids=[class_ids[c] for c in self.uris(iri, OWL.equivalentClass) if c in class_ids and c != iri],
            disjoint_ids=[class_ids[c] for c in self.uris(iri, OWL.disjointWith) if c in class_ids and c != iri],
            restrictions=restrictions,
        )
        return ClassDefinition(
            id=element_id, local_name=local_name, iri=str(iri), parent_ids=parents, semantics=semantics, **base
        )

    def _restriction(
        self,
        node: BNode,
        class_ids: dict[URIRef, str],
        object_ids: dict[URIRef, str],
        datatype_ids: dict[URIRef, str],
        datatypes: dict[URIRef, XsdDatatype | None],
    ) -> Restriction | None:
        g = self.graph
        if len(list(g.subject_predicates(node))) != 1:
            return None
        pairs = list(g.predicate_objects(node))
        if (RDF.type, OWL.Restriction) not in pairs:
            return None
        on_property = [o for p, o in pairs if p == OWL.onProperty]
        if len(on_property) != 1 or not isinstance(on_property[0], URIRef):
            return None
        prop = on_property[0]
        is_object = prop in object_ids
        if not is_object and prop not in datatype_ids:
            return None
        rest = {p: o for p, o in pairs if p not in (RDF.type, OWL.onProperty)}
        if len(rest) != len([p for p, _ in pairs if p not in (RDF.type, OWL.onProperty)]) or len(
            [p for p, _ in pairs if p == RDF.type]
        ) != 1:
            return None
        property_id = object_ids[prop] if is_object else datatype_ids[prop]

        def filler(term: Any) -> dict[str, Any] | None:
            if is_object and isinstance(term, URIRef) and term in class_ids:
                return {"class_id": class_ids[term]}
            if not is_object and term in _XSD_TYPES:
                return {"datatype": _XSD_TYPES[term]}
            return None

        if set(rest) in ({OWL.someValuesFrom}, {OWL.allValuesFrom}):
            predicate, term = next(iter(rest.items()))
            fill = filler(term)
            kind = "some" if predicate == OWL.someValuesFrom else "all"
            return Restriction(property_id=property_id, kind=kind, **fill) if fill else None
        if set(rest) == {OWL.hasValue}:
            value = rest[OWL.hasValue]
            if is_object and isinstance(value, URIRef):
                return Restriction(property_id=property_id, kind="has_value", value=str(value))
            datatype = datatypes.get(prop)
            if not is_object and datatype and isinstance(value, Literal) and value.datatype == XSD[datatype.value]:
                return Restriction(property_id=property_id, kind="has_value", value=str(value))
            return None
        cardinality = [p for p in rest if p in _CARDINALITY]
        if len(cardinality) != 1:
            return None
        kind, qualified = _CARDINALITY[cardinality[0]]
        count = rest[cardinality[0]]
        if not isinstance(count, Literal) or count.datatype != XSD.nonNegativeInteger:
            return None
        try:
            number = int(count)
        except (TypeError, ValueError):
            return None
        if str(Literal(number, datatype=XSD.nonNegativeInteger)) != str(count):
            return None
        if not qualified:
            return Restriction(property_id=property_id, kind=kind, cardinality=number) if len(rest) == 1 else None
        qualifier = OWL.onClass if is_object else OWL.onDataRange
        if set(rest) != {cardinality[0], qualifier}:
            return None
        fill = filler(rest[qualifier])
        return Restriction(property_id=property_id, kind=kind, cardinality=number, **fill) if fill else None

    def _object_property(
        self,
        iri: URIRef,
        element_id: str,
        local_name: str,
        class_ids: dict[URIRef, str],
        object_ids: dict[URIRef, str],
    ) -> ObjectPropertyDefinition:
        base = self._annotations(iri, local_name)
        types = set(self.graph.objects(iri, RDF.type))
        semantics = ObjectPropertySemantics(
            **base.pop("semantics"),
            parent_ids=[object_ids[p] for p in self.uris(iri, RDFS.subPropertyOf) if p in object_ids and p != iri],
            inverse_id=self.single(iri, OWL.inverseOf, object_ids),
            characteristics=sorted(c for t, c in _CHARACTERISTIC_BY_TYPE.items() if t in types),
            equivalent_ids=[object_ids[p] for p in self.uris(iri, OWL.equivalentProperty) if p in object_ids and p != iri],
        )
        return ObjectPropertyDefinition(
            id=element_id,
            local_name=local_name,
            iri=str(iri),
            domain_id=self.single(iri, RDFS.domain, class_ids),
            range_id=self.single(iri, RDFS.range, class_ids),
            semantics=semantics,
            **base,
        )

    def _datatype_property(
        self,
        iri: URIRef,
        element_id: str,
        local_name: str,
        class_ids: dict[URIRef, str],
        datatype_ids: dict[URIRef, str],
        datatype: XsdDatatype | None,
    ) -> DatatypePropertyDefinition:
        base = self._annotations(iri, local_name)
        functional = (iri, RDF.type, OWL.FunctionalProperty) in self.graph
        semantics = DatatypePropertySemantics(
            **base.pop("semantics"),
            parent_ids=[datatype_ids[p] for p in self.uris(iri, RDFS.subPropertyOf) if p in datatype_ids and p != iri],
            functional=functional,
            range_declared=datatype is not None,
            equivalent_ids=[
                datatype_ids[p] for p in self.uris(iri, OWL.equivalentProperty) if p in datatype_ids and p != iri
            ],
        )
        return DatatypePropertyDefinition(
            id=element_id,
            local_name=local_name,
            iri=str(iri),
            domain_id=self.single(iri, RDFS.domain, class_ids),
            datatype=datatype or XsdDatatype.STRING,
            required=False,
            multi_valued=not functional,
            semantics=semantics,
            **base,
        )

    # -------------------------------------------------------------------------- reconciliation

    def _reconcile(self, typed: OntologySnapshot, onto: URIRef | None, ids: dict[URIRef, str]) -> ImportResult:
        source = self.graph
        regenerated = snapshot_to_owl(typed, include_axioms=False)
        regenerated_keys = Counter(
            canonical_component(c) for c in bnode_components(regenerated) if has_bnode(c[0])
        )
        source_keys: Counter[str] = Counter()
        residual: list[list[Triple]] = []
        superseded: list[Triple] = []
        consumed = 0
        for component in bnode_components(source):
            if len(component) == 1 and not has_bnode(component[0]):
                triple = component[0]
                if onto is not None and triple[0] == onto and triple[1] in _SUPERSEDED_HEADER:
                    superseded.append(triple)
                elif triple in regenerated:
                    consumed += 1
                else:
                    residual.append(component)
                continue
            key = canonical_component(component)
            source_keys[key] += 1
            if regenerated_keys[key] > 0:
                regenerated_keys[key] -= 1
                consumed += len(component)
            else:
                residual.append(component)

        added = [t for t in regenerated if not has_bnode(t) and t not in source]
        added_components = sum(regenerated_keys.values())
        unexpected = [
            t for t in added
            if t[1] not in _BOOKKEEPING
            and not (t[1] == RDFS.label and t[0] in ids)
            and not (t[1] == RDF.type and t[2] in (OWL.Class, OWL.Ontology))
            and not (onto is None and t[0] == ontology_iri_of(typed))
        ]
        if onto is None:
            self.warnings.append("The document has no owl:Ontology header; one was created from the namespace.")
        if unexpected or added_components:
            self.warnings.append(
                f"{len(unexpected) + added_components} triple(s) are added by the typed model beyond documented "
                "bookkeeping; review them in the report."
            )

        id_by_iri = {str(iri): element_id for iri, element_id in ids.items()}
        axioms = self._axioms(residual, id_by_iri)
        schema = typed.to_schema().model_copy(update={"extension_axioms": axioms})
        final = typed.model_copy(update={"extension_axioms": axioms})
        lossless = self._verify(final, superseded)
        if not lossless:  # pragma: no cover - a failed guarantee is a defect, never a silent loss
            raise BusinessRuleError(
                "Import aborted: the export would not reproduce every source triple.", code="RDF_IMPORT_LOSSY"
            )

        report = ImportReport(
            rdf_format=self.rdf_format,
            source_triples=len(source),
            consumed_triples=consumed,
            preserved_triples=sum(len(c) for c in residual),
            superseded_triples=len(superseded),
            added_triples=len(added) + added_components,
            classes=len(typed.classes),
            object_properties=len(typed.object_properties),
            datatype_properties=len(typed.datatype_properties),
            preserved_axioms=len(axioms),
            preserved_by_kind=dict(sorted(Counter(a.kind for a in axioms).items())),
            superseded=to_ntriples(superseded).splitlines()[:MAX_REPORTED_TRIPLES] if superseded else [],
            added=to_ntriples(added).splitlines()[:MAX_REPORTED_TRIPLES] if added else [],
            warnings=self.warnings,
            lossless=lossless,
        )
        return ImportResult(metadata=typed.metadata, schema=schema, report=report)

    def _verify(self, final: OntologySnapshot, superseded: list[Triple]) -> bool:
        """The version package (OWL export + preserved shapes) must contain every source triple."""
        exported = snapshot_to_owl(final)
        for axiom in final.extension_axioms:
            if axiom.scope == "shapes":
                load_ntriples(exported, axiom.ntriples)
        exported_keys = Counter(canonical_component(c) for c in bnode_components(exported) if has_bnode(c[0]))
        skip = set(superseded)
        for component in bnode_components(self.graph):
            if len(component) == 1 and not has_bnode(component[0]):
                if component[0] not in skip and component[0] not in exported:
                    return False
                continue
            key = canonical_component(component)
            if exported_keys[key] <= 0:
                return False
            exported_keys[key] -= 1
        return True

    def _axioms(self, residual: list[list[Triple]], id_by_iri: dict[str, str]) -> list[ExtensionAxiom]:
        shape_subjects = {
            s for s, p, o in self.graph
            if str(p).startswith(str(SH)) or (p == RDF.type and str(o).startswith(str(SH)))
        }
        self.individuals = {
            s for s, o in self.graph.subject_objects(RDF.type)
            if o == OWL.NamedIndividual or o in self.class_iris
        }
        self.annotation_properties = set(self.graph.subjects(RDF.type, OWL.AnnotationProperty))
        groups: dict[tuple[Any, ...], list[Triple]] = defaultdict(list)
        for component in residual:
            if len(component) == 1 and not has_bnode(component[0]):
                triple = component[0]
                scope = "shapes" if triple[0] in shape_subjects else "ontology"
                groups[("ground", triple[0], scope, self._kind([triple], scope))].extend(component)
            else:
                scope = "shapes" if any(t[0] in shape_subjects for t in component) else "ontology"
                groups[("component", len(groups), scope, self._kind(component, scope))].extend(component)

        axioms: list[ExtensionAxiom] = []
        used: set[str] = set()
        for key, triples in groups.items():
            scope, kind = key[2], key[3]
            ntriples = to_ntriples(triples)
            digest = hashlib.sha256(f"{scope}\n{canonical_component(triples)}".encode()).hexdigest()
            axiom_id, n = f"ax_{digest[:16]}", 2
            while axiom_id in used:
                axiom_id, n = f"ax_{digest[:16]}_{n}", n + 1
            used.add(axiom_id)
            anchors = sorted(
                {id_by_iri[str(term)] for t in triples for term in t if isinstance(term, URIRef) and str(term) in id_by_iri}
            )
            axioms.append(
                ExtensionAxiom(
                    id=axiom_id,
                    scope=scope,
                    kind=kind,
                    summary=self._summary(triples),
                    ntriples=ntriples,
                    anchor_ids=anchors,
                )
            )
        return sorted(axioms, key=lambda a: (a.scope, a.kind, a.summary))

    def _kind(self, triples: list[Triple], scope: str) -> str:
        if scope == "shapes":
            return "shacl-shape"
        predicates = {p for _, p, _ in triples}
        objects = {o for _, p, o in triples if p == RDF.type}
        if any(s in self.individuals for s, _, _ in triples):
            return "individual"
        if OWL.Restriction in objects:
            return "owl-restriction"
        if predicates & _CLASS_EXPRESSION:
            return "owl-class-expression"
        if objects & _NARY:
            return "owl-n-ary-axiom"
        if objects & {OWL.NamedIndividual}:
            return "individual"
        if objects & {OWL.AnnotationProperty}:
            return "annotation-property"
        if objects & {RDFS.Class}:
            return "rdfs-declaration"
        if predicates <= (_ANNOTATION_PREDICATES | self.annotation_properties) or all(
            str(p).startswith((str(SKOS), str(DCTERMS), "http://purl.org/dc/elements/1.1/")) for p in predicates
        ):
            return "annotation"
        if any(str(p).startswith(str(OWL)) for p in predicates) or any(str(o).startswith(str(OWL)) for o in objects):
            return "owl-axiom"
        if predicates & {RDFS.domain, RDFS.range, RDFS.subClassOf, RDFS.subPropertyOf}:
            return "rdfs-axiom"
        return "rdf-statement"

    def _summary(self, triples: list[Triple]) -> str:
        manager = self.graph.namespace_manager

        def short(term: Any) -> str:
            if isinstance(term, BNode):
                return "[]"
            if isinstance(term, Literal):
                text = str(term)
                return f'"{text[:60]}{"..." if len(text) > 60 else ""}"'
            try:
                return term.n3(manager)
            except Exception:  # noqa: BLE001
                return f"<{term}>"

        ordered = sorted(triples, key=lambda t: (isinstance(t[0], BNode), str(t[1])))
        s, p, o = ordered[0]
        extra = f" (+{len(triples) - 1} more triple{'s' if len(triples) > 2 else ''})" if len(triples) > 1 else ""
        return f"{short(s)} {short(p)} {short(o)}{extra}"


def import_graph(
    graph: Graph,
    *,
    rdf_format: str,
    name: str | None = None,
    namespace: str | None = None,
    prefix: str | None = None,
    filename: str | None = None,
) -> ImportResult:
    return _Importer(graph, rdf_format).run(name=name, namespace=namespace, prefix=prefix, filename=filename)
