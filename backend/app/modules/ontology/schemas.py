from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.ontology.domain import (
    Aliases,
    ClassDefinition,
    DatatypePropertyDefinition,
    Description,
    ElementId,
    Label,
    LocalName,
    ObjectPropertyDefinition,
    ParentIds,
    PrefixBinding,
    XsdDatatype,
)

OntologyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Namespace = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Prefix = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------- ontology


class OntologyMetadata(_Strict):
    name: OntologyName
    namespace: Namespace
    prefix: Prefix
    description: Description = ""
    # Ontology header (Phase 4). Omitted fields are left unchanged on draft save.
    ontology_iri: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    prefixes: list[PrefixBinding] = Field(default_factory=list, max_length=100)
    imports: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=100
    )
    require_domain_range: bool = True


class OntologyCreate(OntologyMetadata):
    pass


class OntologyUpdate(_Strict):
    name: OntologyName | None = None
    namespace: Namespace | None = None
    prefix: Prefix | None = None
    description: Description | None = None


class OntologyStats(BaseModel):
    class_count: int = 0
    object_property_count: int = 0
    datatype_property_count: int = 0


class PublishedVersionRef(BaseModel):
    id: str
    version: str
    draft_revision: int
    published_at: datetime


class OntologyRead(BaseModel):
    id: str
    project_id: str
    name: str
    namespace: str
    prefix: str
    description: str
    ontology_iri: str | None = None
    prefixes: list[PrefixBinding] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    require_domain_range: bool = True
    draft_revision: int
    stats: OntologyStats
    latest_version: PublishedVersionRef | None = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------- draft document


class Position(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class DiagramLayout(BaseModel):
    """Presentation metadata for the visual designer; keyed by class element id."""

    positions: dict[ElementId, Position] = Field(default_factory=dict)


class OntologyDraft(BaseModel):
    """The full, editable working copy of an ontology."""

    ontology: OntologyRead
    draft_revision: int
    classes: list[ClassDefinition]
    object_properties: list[ObjectPropertyDefinition]
    datatype_properties: list[DatatypePropertyDefinition]
    layout: DiagramLayout


class DraftSaveRequest(_Strict):
    base_revision: int = Field(ge=1, description="Draft revision the client edited (optimistic lock).")
    metadata: OntologyMetadata
    classes: list[ClassDefinition] = Field(default_factory=list, max_length=2000)
    object_properties: list[ObjectPropertyDefinition] = Field(default_factory=list, max_length=5000)
    datatype_properties: list[DatatypePropertyDefinition] = Field(
        default_factory=list, max_length=10000
    )
    layout: DiagramLayout = Field(default_factory=DiagramLayout)


class ElementChangeCounts(BaseModel):
    added: int = 0
    updated: int = 0
    removed: int = 0

    @property
    def total(self) -> int:
        return self.added + self.updated + self.removed


class DraftChangeSummary(BaseModel):
    metadata_changed: bool = False
    classes: ElementChangeCounts = Field(default_factory=ElementChangeCounts)
    object_properties: ElementChangeCounts = Field(default_factory=ElementChangeCounts)
    datatype_properties: ElementChangeCounts = Field(default_factory=ElementChangeCounts)
    layout_changed: bool = False

    @property
    def has_semantic_changes(self) -> bool:
        return (
            self.metadata_changed
            or self.classes.total > 0
            or self.object_properties.total > 0
            or self.datatype_properties.total > 0
        )

    def describe(self) -> str:
        parts: list[str] = []
        if self.metadata_changed:
            parts.append("metadata updated")
        for label, counts in (
            ("class", self.classes),
            ("relationship", self.object_properties),
            ("attribute", self.datatype_properties),
        ):
            for symbol, n in (("+", counts.added), ("~", counts.updated), ("-", counts.removed)):
                if n:
                    parts.append(f"{symbol}{n} {label}{'' if n == 1 else 'es' if label == 'class' else 's'}")
        if not parts and self.layout_changed:
            parts.append("diagram layout only")
        return ", ".join(parts) if parts else "no changes"


class DraftSaveResponse(BaseModel):
    draft: OntologyDraft
    changes: DraftChangeSummary
    revision_incremented: bool


class ClassDeletionResult(BaseModel):
    deleted_class_id: str
    removed_object_property_ids: list[str]
    removed_datatype_property_ids: list[str]
    detached_child_class_ids: list[str]
    draft_revision: int


# ----------------------------------------------------------------------------- granular element commands


class ClassCreate(_Strict):
    id: ElementId | None = None
    local_name: LocalName | None = None
    label: Label
    description: Description = ""
    aliases: Aliases = Field(default_factory=list)
    parent_ids: ParentIds = Field(default_factory=list)
    position: Position | None = None


class ClassUpdate(_Strict):
    local_name: LocalName | None = None
    label: Label | None = None
    description: Description | None = None
    aliases: Aliases | None = None
    parent_ids: ParentIds | None = None


class ObjectPropertyCreate(_Strict):
    id: ElementId | None = None
    local_name: LocalName | None = None
    label: Label
    description: Description = ""
    aliases: Aliases = Field(default_factory=list)
    domain_id: ElementId
    range_id: ElementId


class ObjectPropertyUpdate(_Strict):
    local_name: LocalName | None = None
    label: Label | None = None
    description: Description | None = None
    aliases: Aliases | None = None
    domain_id: ElementId | None = None
    range_id: ElementId | None = None


class DatatypePropertyCreate(_Strict):
    id: ElementId | None = None
    local_name: LocalName | None = None
    label: Label
    description: Description = ""
    aliases: Aliases = Field(default_factory=list)
    domain_id: ElementId
    datatype: XsdDatatype = XsdDatatype.STRING
    required: bool = False
    multi_valued: bool = False


class DatatypePropertyUpdate(_Strict):
    local_name: LocalName | None = None
    label: Label | None = None
    description: Description | None = None
    aliases: Aliases | None = None
    domain_id: ElementId | None = None
    datatype: XsdDatatype | None = None
    required: bool | None = None
    multi_valued: bool | None = None
