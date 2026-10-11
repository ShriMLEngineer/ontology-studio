from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ConfigDict, StringConstraints

from app.modules.registry.diff import SchemaDiff
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.validation.schemas import ValidationIssue


class VersionArtifactRead(BaseModel):
    format: str
    filename: str
    media_type: str
    sha256: str
    size: int


class VersionSummary(BaseModel):
    id: str
    ontology_id: str
    version: str
    sequence: int
    draft_revision: int
    content_hash: str
    class_count: int
    object_property_count: int
    datatype_property_count: int
    change_summary: dict[str, Any]
    validation_summary: dict[str, Any]
    previous_version_id: str | None
    release_notes: str
    published_by: str
    published_at: datetime
    artifacts: list[VersionArtifactRead]
    snapshot_format: str = "ols.ontology-snapshot/1"
    package_format: str = Field(
        default="ols-semantic/1 (legacy)",
        description="ols-semantic/2 packages carry OWL in four RDF syntaxes and a manifest; legacy versions "
        "stored Turtle and JSON only (other syntaxes are derived on export, never stored).",
    )


class VersionDetail(VersionSummary):
    snapshot: OntologySnapshot


class PublishValidation(BaseModel):
    is_valid: bool
    error_count: int
    warning_count: int
    info_count: int
    blocking_issues: list[ValidationIssue]


class PublishPreview(BaseModel):
    ontology_id: str
    draft_revision: int
    latest_version: VersionSummary | None
    validation: PublishValidation
    diff: SchemaDiff
    suggested_version: str
    can_publish: bool
    blockers: list[str]
    proposals_awaiting_review: int
    proposals_approved_not_applied: int


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published_by: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    release_notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""
    version: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    bump: Literal["major", "minor", "patch"] | None = None
    expected_draft_revision: int | None = None
