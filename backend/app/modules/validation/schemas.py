from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ElementKind(StrEnum):
    ONTOLOGY = "ontology"
    CLASS = "class"
    OBJECT_PROPERTY = "object_property"
    DATATYPE_PROPERTY = "datatype_property"


class ValidationIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    element_kind: ElementKind
    element_id: str | None = None
    element_label: str | None = None
    field: str | None = None
    related_element_ids: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    id: str
    ontology_id: str
    draft_revision: int
    current_draft_revision: int
    is_current: bool = Field(description="True when the report reflects the latest saved draft.")
    is_valid: bool = Field(description="True when there are no error-severity issues.")
    error_count: int
    warning_count: int
    info_count: int
    issues: list[ValidationIssue]
    created_at: datetime
