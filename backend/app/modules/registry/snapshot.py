"""Canonical, deterministic ontology snapshots used for publishing, hashing and comparison."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ExtensionAxiom,
    NodeShape,
    ObjectPropertyDefinition,
    OntologySchema,
    PrefixBinding,
    element_iri,
)

LEGACY_FORMAT = "ols.ontology-snapshot/1"
SNAPSHOT_FORMAT = "ols.ontology-snapshot/2"


class SnapshotMetadata(BaseModel):
    name: str
    namespace: str
    prefix: str
    description: str = ""
    ontology_iri: str | None = None
    prefixes: list[PrefixBinding] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    require_domain_range: bool = True


class OntologySnapshot(BaseModel):
    """Format /1 = legacy (read-only); /2 adds IRIs, header, semantics,
    preserved axioms and SHACL shapes."""

    format: Literal["ols.ontology-snapshot/1", "ols.ontology-snapshot/2"] = SNAPSHOT_FORMAT
    metadata: SnapshotMetadata
    classes: list[ClassDefinition] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDefinition] = Field(default_factory=list)
    datatype_properties: list[DatatypePropertyDefinition] = Field(default_factory=list)
    extension_axioms: list[ExtensionAxiom] = Field(default_factory=list)
    shapes: list[NodeShape] = Field(default_factory=list)

    @property
    def is_legacy(self) -> bool:
        return self.format == LEGACY_FORMAT

    def to_schema(self) -> OntologySchema:
        return OntologySchema(
            namespace=self.metadata.namespace,
            prefix=self.metadata.prefix,
            ontology_iri=self.metadata.ontology_iri,
            prefixes=self.metadata.prefixes,
            imports=self.metadata.imports,
            require_domain_range=self.metadata.require_domain_range,
            classes=self.classes,
            object_properties=self.object_properties,
            datatype_properties=self.datatype_properties,
            extension_axioms=self.extension_axioms,
            shapes=self.shapes,
        )

    def with_iris(self) -> "OntologySnapshot":
        """Copy with every element IRI made explicit (legacy snapshots derive them)."""
        ns = self.metadata.namespace
        return self.model_copy(
            update={
                key: [e.model_copy(update={"iri": element_iri(ns, e)}) for e in getattr(self, key)]
                for key in ("classes", "object_properties", "datatype_properties")
            }
        )


def metadata_from_ontology(ontology: Any) -> SnapshotMetadata:
    """Snapshot header of a persisted ontology draft (``app.modules.ontology.models.Ontology``)."""
    return SnapshotMetadata(
        name=ontology.name,
        namespace=ontology.namespace,
        prefix=ontology.prefix,
        description=ontology.description,
        ontology_iri=ontology.ontology_iri,
        prefixes=ontology.prefixes or [],
        imports=ontology.imports or [],
        require_domain_range=ontology.require_domain_range,
    )


def build_snapshot(metadata: SnapshotMetadata, schema: OntologySchema) -> OntologySnapshot:
    """Elements are sorted by stable id so equal content always produces equal bytes."""
    return OntologySnapshot(
        metadata=metadata,
        classes=sorted(schema.classes, key=lambda e: e.id),
        object_properties=sorted(schema.object_properties, key=lambda e: e.id),
        datatype_properties=sorted(schema.datatype_properties, key=lambda e: e.id),
        extension_axioms=sorted(schema.extension_axioms, key=lambda a: a.id),
        shapes=sorted(schema.shapes, key=lambda s: s.id),
    )


def canonical_json(snapshot: OntologySnapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(snapshot: OntologySnapshot) -> str:
    return hashlib.sha256(canonical_json(snapshot)).hexdigest()
