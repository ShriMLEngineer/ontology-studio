from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.ontology.schemas import DraftChangeSummary
from app.modules.validation.schemas import ValidationIssue

ProposalType = Literal["add", "reuse", "alias", "modify", "conflict"]
ProposalStatus = Literal["pending", "approved", "rejected", "needs_refinement", "applied"]
ElementKind = Literal["class", "object_property", "datatype_property"]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str | None
    document_name: str
    chunk_id: str | None
    page: int | None
    quote: str
    context: str
    start_offset: int | None
    end_offset: int | None
    verified: bool
    created_at: datetime


class ProposalEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    actor: str
    comment: str
    details: dict[str, Any]
    created_at: datetime


class ProposalSummary(BaseModel):
    id: str
    ontology_id: str
    run_id: str | None
    proposal_type: ProposalType
    element_kind: ElementKind
    status: ProposalStatus
    title: str
    term: str
    confidence: float | None
    target_element_id: str | None
    target_label: str | None
    evidence_count: int
    edited: bool
    applied_draft_revision: int | None
    apply_error: str | None
    created_at: datetime
    updated_at: datetime


class ProposalImpact(BaseModel):
    applicable: bool
    reason: str | None
    blocking: bool
    introduced_issues: list[ValidationIssue]
    resolved_issues: list[ValidationIssue]


class ProposalDetail(ProposalSummary):
    rationale: str
    new_element: dict[str, Any] | None
    changes: dict[str, dict[str, Any]]
    alignment: dict[str, Any]
    depends_on: list[str]
    llm_output: dict[str, Any] | None
    target: dict[str, Any] | None = Field(description="Current draft definition of the target element")
    evidence: list[EvidenceRead]
    events: list[ProposalEventRead]
    impact: ProposalImpact | None


class ProposalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: Actor
    comment: Comment = ""
    proposal_type: ProposalType | None = None
    target_element_id: str | None = None
    new_element: dict[str, Any] | None = None
    after: dict[str, Any] | None = Field(
        default=None, description="MODIFY/CONFLICT: new field values; 'before' is taken from the current draft"
    )
    alias: str | None = None
    rationale: Comment | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "request_refinement", "reopen"]
    actor: Actor
    comment: Comment = ""


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: Actor
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: Actor
    proposal_ids: list[str] | None = Field(default=None, description="Defaults to every approved proposal")


class ApplyFailure(BaseModel):
    proposal_id: str
    title: str
    reason: str


class ApplyResult(BaseModel):
    applied: list[ProposalSummary]
    failed: list[ApplyFailure]
    draft_revision: int
    revision_incremented: bool
    changes: DraftChangeSummary


class ProposalStats(BaseModel):
    total: int
    awaiting_review: int
    approved_not_applied: int
    by_status: dict[str, int]
    by_type: dict[str, int]
