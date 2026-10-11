from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.discovery.schemas import DiscoveryRunCreate, DiscoveryRunRead
from app.modules.discovery.service import DiscoveryService, execute_discovery_run
from app.modules.llm.provider import LLMProvider
from app.modules.llm.service import require_llm_provider

router = APIRouter(tags=["discovery"])


def get_discovery_service(session: Annotated[Session, Depends(get_session)]) -> DiscoveryService:
    return DiscoveryService(session)


Service = Annotated[DiscoveryService, Depends(get_discovery_service)]


@router.post(
    "/ontologies/{ontology_id}/discovery-runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_discovery(
    ontology_id: str,
    data: DiscoveryRunCreate,
    request: Request,
    background: BackgroundTasks,
    service: Service,
    provider: Annotated[LLMProvider, Depends(require_llm_provider)],
) -> DiscoveryRunRead:
    """Queue an AI discovery run. Poll the run until it is ``completed`` or ``failed``."""
    run = service.create_run(ontology_id, data, provider)
    background.add_task(
        execute_discovery_run, request.app.state.session_factory, provider, request.app.state.settings, run.id
    )
    return run


@router.get("/ontologies/{ontology_id}/discovery-runs", response_model=list[DiscoveryRunRead])
def list_discovery_runs(ontology_id: str, service: Service) -> list[DiscoveryRunRead]:
    return service.list_runs(ontology_id)


@router.get("/discovery-runs/{run_id}", response_model=DiscoveryRunRead)
def get_discovery_run(run_id: str, service: Service) -> DiscoveryRunRead:
    return service.get_run(run_id)
