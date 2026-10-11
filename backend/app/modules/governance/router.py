from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.governance.schemas import (
    ApplyRequest,
    ApplyResult,
    CommentCreate,
    DecisionRequest,
    ProposalDetail,
    ProposalEventRead,
    ProposalStats,
    ProposalSummary,
    ProposalUpdate,
)
from app.modules.governance.service import GovernanceService

router = APIRouter(tags=["governance"])


def get_governance_service(session: Annotated[Session, Depends(get_session)]) -> GovernanceService:
    return GovernanceService(session)


Service = Annotated[GovernanceService, Depends(get_governance_service)]


@router.get("/ontologies/{ontology_id}/proposals", response_model=list[ProposalSummary])
def list_proposals(
    ontology_id: str,
    service: Service,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    proposal_type: Annotated[str | None, Query(alias="type")] = None,
    run_id: str | None = None,
) -> list[ProposalSummary]:
    return service.list_proposals(ontology_id, status=status_filter, proposal_type=proposal_type, run_id=run_id)


@router.get("/ontologies/{ontology_id}/proposals/stats", response_model=ProposalStats)
def proposal_stats(ontology_id: str, service: Service) -> ProposalStats:
    return service.stats(ontology_id)


@router.post("/ontologies/{ontology_id}/proposals/apply", response_model=ApplyResult)
def apply_approved(ontology_id: str, data: ApplyRequest, service: Service) -> ApplyResult:
    """Apply approved proposals to the editable draft (never to a published version)."""
    return service.apply_approved(ontology_id, data)


@router.get("/proposals/{proposal_id}", response_model=ProposalDetail)
def get_proposal(proposal_id: str, service: Service) -> ProposalDetail:
    return service.get_proposal(proposal_id)


@router.patch("/proposals/{proposal_id}", response_model=ProposalDetail)
def update_proposal(proposal_id: str, data: ProposalUpdate, service: Service) -> ProposalDetail:
    return service.update_proposal(proposal_id, data)


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalDetail)
def decide(proposal_id: str, data: DecisionRequest, service: Service) -> ProposalDetail:
    return service.decide(proposal_id, data)


@router.post(
    "/proposals/{proposal_id}/comments", response_model=ProposalEventRead, status_code=status.HTTP_201_CREATED
)
def add_comment(proposal_id: str, data: CommentCreate, service: Service) -> ProposalEventRead:
    return service.add_comment(proposal_id, data)
