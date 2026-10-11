from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class DiscoveryRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(min_length=1, max_length=20)
    baseline_version_id: str | None = Field(
        default=None, description="Analyse against a published version instead of the current draft"
    )
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    requested_by: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class RunDocument(BaseModel):
    id: str
    filename: str | None


class DiscoveryRunRead(BaseModel):
    id: str
    ontology_id: str
    status: str
    baseline_kind: str
    baseline_label: str
    baseline_version_id: str | None
    baseline_draft_revision: int | None
    documents: list[RunDocument]
    instructions: str
    provider: str
    model: str
    prompt_version: str
    progress: dict[str, Any]
    stats: dict[str, Any]
    discarded: list[dict[str, Any]]
    usage: dict[str, Any]
    error: str | None
    requested_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
