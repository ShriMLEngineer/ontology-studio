from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.discovery.schemas import DiscoveryRunCreate, DiscoveryRunRead
from app.modules.discovery.service import DiscoveryService, execute_discovery_run
from app.core.errors import UnavailableError
from app.modules.llm.provider import LLMNotConfiguredError
from app.modules.ontology.service import OntologyService
from app.modules.settings.router import get_settings_service
from app.modules.settings.service import SettingsService

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
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
) -> DiscoveryRunRead:
    """Queue an AI discovery run with the selected (or the project's default) LLM configuration.
    Poll the run until it is ``completed`` or ``failed``."""
    settings_service.require_llm_id(data.llm_config_id)
    ontology = OntologyService(settings_service.session)._require(ontology_id)
    provider = settings_service.provider_for(settings_service.effective_llm_id(ontology.project_id, data.llm_config_id))
    if provider is None:
        raise UnavailableError(
            "No LLM is available: register an LLM configuration in Settings or configure the environment default "
            "(OLS_LLM_BASE_URL, OLS_LLM_MODEL).",
            code=LLMNotConfiguredError.code,
        )
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
