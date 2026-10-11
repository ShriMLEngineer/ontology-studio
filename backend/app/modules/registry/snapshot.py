"""Canonical, deterministic ontology snapshots used for publishing, hashing and comparison."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
)

SNAPSHOT_FORMAT = "ols.ontology-snapshot/1"


class SnapshotMetadata(BaseModel):
    name: str
    namespace: str
    prefix: str
    description: str = ""


class OntologySnapshot(BaseModel):
    format: Literal["ols.ontology-snapshot/1"] = SNAPSHOT_FORMAT
    metadata: SnapshotMetadata
    classes: list[ClassDefinition] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDefinition] = Field(default_factory=list)
    datatype_properties: list[DatatypePropertyDefinition] = Field(default_factory=list)

    def to_schema(self) -> OntologySchema:
        return OntologySchema(
            namespace=self.metadata.namespace,
            prefix=self.metadata.prefix,
            classes=self.classes,
            object_properties=self.object_properties,
            datatype_properties=self.datatype_properties,
        )


def build_snapshot(metadata: SnapshotMetadata, schema: OntologySchema) -> OntologySnapshot:
    """Elements are sorted by stable id so equal content always produces equal bytes."""
    return OntologySnapshot(
        metadata=metadata,
        classes=sorted(schema.classes, key=lambda e: e.id),
        object_properties=sorted(schema.object_properties, key=lambda e: e.id),
        datatype_properties=sorted(schema.datatype_properties, key=lambda e: e.id),
    )


def canonical_json(snapshot: OntologySnapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(snapshot: OntologySnapshot) -> str:
    return hashlib.sha256(canonical_json(snapshot)).hexdigest()
