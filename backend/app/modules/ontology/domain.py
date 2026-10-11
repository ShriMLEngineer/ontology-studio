"""Canonical ontology schema model.

This model is the single source of truth for ontology *schema* (TBox) content. It is
independent of persistence (SQLAlchemy), presentation (React Flow), LLM output formats and
graph databases. Knowledge-graph instance facts (ABox) are modelled separately (Phase 3).
"""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

ELEMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$"

ElementId = Annotated[str, StringConstraints(pattern=ELEMENT_ID_PATTERN, max_length=64)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LocalName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


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


class _Element(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ElementId
    local_name: LocalName
    label: Label
    description: Description = ""
    aliases: Aliases = Field(default_factory=list)


class ClassDefinition(_Element):
    """An ontology class (owl:Class). ``parent_ids`` expresses rdfs:subClassOf."""

    parent_ids: ParentIds = Field(default_factory=list)


class ObjectPropertyDefinition(_Element):
    """A directed relationship (owl:ObjectProperty) from a domain class to a range class."""

    domain_id: ElementId | None = None
    range_id: ElementId | None = None


class DatatypePropertyDefinition(_Element):
    """A literal-valued attribute (owl:DatatypeProperty) of a domain class."""

    domain_id: ElementId | None = None
    datatype: XsdDatatype = XsdDatatype.STRING
    required: bool = False
    multi_valued: bool = False


class OntologySchema(BaseModel):
    """A complete, self-contained ontology schema snapshot."""

    namespace: str
    prefix: str
    classes: list[ClassDefinition] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDefinition] = Field(default_factory=list)
    datatype_properties: list[DatatypePropertyDefinition] = Field(default_factory=list)


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
