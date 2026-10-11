"""Canonical ontology schema model.

This model is the authoritative representation of the constructs in the *OLS Semantic Profile*
(a documented subset of OWL 2). Constructs outside the profile are kept verbatim as
:class:`ExtensionAxiom` triples so that nothing imported is silently discarded. The model is
independent of persistence (SQLAlchemy), presentation (React Flow), LLM output formats and
graph databases. Knowledge-graph instance facts (ABox) are modelled separately.
"""

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ELEMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$"

ElementId = Annotated[str, StringConstraints(pattern=ELEMENT_ID_PATTERN, max_length=64)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LocalName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
Iri = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
LanguageTag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$")]


def _normalize_aliases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        alias = raw.strip()
        key = alias.casefold()
        if alias and key not in seen:
            seen.add(key)
            result.append(alias)
    return result


Aliases = Annotated[
    list[Annotated[str, StringConstraints(max_length=200)]],
    Field(max_length=50),
    AfterValidator(_normalize_aliases),
]


def _dedupe_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


ParentIds = Annotated[list[ElementId], Field(max_length=20), AfterValidator(_dedupe_ids)]


class XsdDatatype(StrEnum):
    """Literal datatypes supported for datatype properties (XML Schema datatypes)."""

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATE_TIME = "dateTime"
    ANY_URI = "anyURI"
    FLOAT = "float"
    DOUBLE = "double"
    INT = "int"
    LONG = "long"
    TIME = "time"
    G_YEAR = "gYear"


IdList = Annotated[list[ElementId], Field(max_length=50), AfterValidator(_dedupe_ids)]
Characteristic = Literal[
    "functional", "inverse_functional", "transitive", "symmetric", "asymmetric", "reflexive", "irreflexive"
]
RestrictionKind = Literal["some", "all", "has_value", "min", "max", "exact"]


class Restriction(BaseModel):
    """An OWL property restriction used as a superclass of the owning class
    (``Class rdfs:subClassOf [owl:onProperty p; ...]``)."""

    model_config = ConfigDict(extra="forbid")

    property_id: ElementId
    kind: RestrictionKind
    class_id: ElementId | None = Field(default=None, description="Filler (some/all) or qualifying class")
    datatype: XsdDatatype | None = Field(default=None, description="Data filler (some/all) or qualifying datatype")
    value: str | None = Field(default=None, max_length=1000, description="Literal or IRI for has_value")
    cardinality: int | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode="after")
    def _check_shape(self) -> "Restriction":
        if self.kind in ("some", "all") and not (self.class_id or self.datatype):
            raise ValueError("some/all restrictions need a class or datatype filler")
        if self.kind == "has_value" and self.value is None:
            raise ValueError("has_value restrictions need a value")
        if self.kind in ("min", "max", "exact") and self.cardinality is None:
            raise ValueError("cardinality restrictions need a cardinality")
        if self.class_id and self.datatype:
            raise ValueError("use either class_id or datatype, not both")
        return self


class _Semantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deprecated: bool = False
    equivalent_ids: IdList = Field(default_factory=list)
    annotation_language: LanguageTag | None = Field(
        default=None, description="Language tag of label, description and aliases (None = plain literals)"
    )
    description_predicate: Literal["skos:definition", "rdfs:comment"] = "skos:definition"


class ClassSemantics(_Semantics):
    disjoint_ids: IdList = Field(default_factory=list)
    restrictions: list[Restriction] = Field(default_factory=list, max_length=100)


class ObjectPropertySemantics(_Semantics):
    parent_ids: IdList = Field(default_factory=list, description="rdfs:subPropertyOf")
    inverse_id: ElementId | None = None
    characteristics: list[Characteristic] = Field(default_factory=list)


class DatatypePropertySemantics(_Semantics):
    parent_ids: IdList = Field(default_factory=list, description="rdfs:subPropertyOf")
    functional: bool = Field(
        default=False,
        description="Assert owl:FunctionalProperty. Independent of the single-value data constraint (SHACL).",
    )
    range_declared: bool = Field(default=True, description="Emit rdfs:range for the datatype")


class _Element(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ElementId
    local_name: LocalName
    label: Label
    description: Description = ""
    aliases: Aliases = Field(default_factory=list)
    iri: Iri | None = Field(default=None, description="Persisted IRI; locked once the element is published")


class ClassDefinition(_Element):
    """An ontology class (owl:Class). ``parent_ids`` expresses rdfs:subClassOf."""

    parent_ids: ParentIds = Field(default_factory=list)
    semantics: ClassSemantics = Field(default_factory=ClassSemantics)


class ObjectPropertyDefinition(_Element):
    """A directed relationship (owl:ObjectProperty) from a domain class to a range class."""

    domain_id: ElementId | None = None
    range_id: ElementId | None = None
    semantics: ObjectPropertySemantics = Field(default_factory=ObjectPropertySemantics)


class DatatypePropertyDefinition(_Element):
    """A literal-valued attribute (owl:DatatypeProperty) of a domain class."""

    domain_id: ElementId | None = None
    datatype: XsdDatatype = XsdDatatype.STRING
    # Data constraints validated with SHACL (minCount / maxCount) - not OWL axioms.
    required: bool = False
    multi_valued: bool = False
    semantics: DatatypePropertySemantics = Field(default_factory=DatatypePropertySemantics)


class PrefixBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: Annotated[str, StringConstraints(pattern=r"^([A-Za-z_][A-Za-z0-9_.\-]{0,39})?$")]
    namespace: Iri


class ExtensionAxiom(BaseModel):
    """Triples outside the OLS Semantic Profile, preserved verbatim (N-Triples, blank-node closure)."""

    id: str
    scope: Literal["ontology", "shapes"] = "ontology"
    kind: str
    summary: str
    ntriples: str
    anchor_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------------- SHACL shapes (Phase 4.2)

ShapeSeverity = Literal["Violation", "Warning", "Info"]
NodeKind = Literal["IRI", "Literal", "BlankNode", "BlankNodeOrIRI", "BlankNodeOrLiteral", "IRIOrLiteral"]
ShapeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")]
ShapeText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class PropertyConstraint(BaseModel):
    """A property shape on one ontology property (simple ``sh:path``)."""

    model_config = ConfigDict(extra="forbid")

    id: ShapeId
    path_id: ElementId = Field(description="Object or datatype property id used as sh:path")
    min_count: int | None = Field(default=None, ge=0, le=100000)
    max_count: int | None = Field(default=None, ge=0, le=100000)
    datatype: XsdDatatype | None = None
    class_id: ElementId | None = Field(default=None, description="sh:class (relationships)")
    node_kind: NodeKind | None = None
    allowed_values: list[Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=list, max_length=200, description="sh:in (literals or IRIs)"
    )
    pattern: Annotated[str, StringConstraints(max_length=500)] | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    min_inclusive: Annotated[str, StringConstraints(max_length=100)] | None = None
    max_inclusive: Annotated[str, StringConstraints(max_length=100)] | None = None
    severity: ShapeSeverity | None = Field(default=None, description="Overrides the node shape severity")
    message: ShapeText = ""

    @field_validator("pattern")
    @classmethod
    def _valid_regex(cls, value: str | None) -> str | None:
        if value:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}") from exc
        return value or None

    @model_validator(mode="after")
    def _ranges(self) -> "PropertyConstraint":
        if self.min_count is not None and self.max_count is not None and self.min_count > self.max_count:
            raise ValueError("min_count must not exceed max_count")
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("min_length must not exceed max_length")
        return self

    def is_empty(self) -> bool:
        return not any(
            (
                self.min_count is not None,
                self.max_count is not None,
                self.datatype,
                self.class_id,
                self.node_kind,
                self.allowed_values,
                self.pattern,
                self.min_length is not None,
                self.max_length is not None,
                self.min_inclusive,
                self.max_inclusive,
            )
        )


class NodeShape(BaseModel):
    """An authored node shape targeting one ontology class (``sh:targetClass``)."""

    model_config = ConfigDict(extra="forbid")

    id: ShapeId
    target_class_id: ElementId
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: ShapeText = ""
    severity: ShapeSeverity = "Violation"
    message: ShapeText = ""
    deactivated: bool = False
    properties: list[PropertyConstraint] = Field(default_factory=list, max_length=200)


class OntologySchema(BaseModel):
    """A complete, self-contained ontology schema snapshot."""

    namespace: str
    prefix: str
    ontology_iri: str | None = None
    prefixes: list[PrefixBinding] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    require_domain_range: bool = True
    classes: list[ClassDefinition] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDefinition] = Field(default_factory=list)
    datatype_properties: list[DatatypePropertyDefinition] = Field(default_factory=list)
    extension_axioms: list[ExtensionAxiom] = Field(default_factory=list)
    shapes: list[NodeShape] = Field(default_factory=list, description="Authored SHACL node shapes")


def default_ontology_iri(namespace: str) -> str:
    return namespace.rstrip("#/:") or namespace


def element_iri(
    namespace: str, element: "ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition"
) -> str:
    """The element's persisted IRI, or the IRI derived from namespace + local name (legacy data)."""
    return element.iri or f"{namespace}{element.local_name}"


_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def _words(label: str) -> list[str]:
    return [w for w in _WORD_SPLIT.split(label.strip()) if w]


def to_class_local_name(label: str) -> str:
    """'purchase order' -> 'PurchaseOrder'"""
    name = "".join(w[:1].upper() + w[1:] for w in _words(label))
    return name if name and not name[0].isdigit() else f"C{name}"


def to_property_local_name(label: str) -> str:
    """'ships to' -> 'shipsTo'"""
    words = _words(label)
    if not words:
        return "p"
    first = words[0][:1].lower() + words[0][1:]
    name = first + "".join(w[:1].upper() + w[1:] for w in words[1:])
    return name if not name[0].isdigit() else f"p{name}"
