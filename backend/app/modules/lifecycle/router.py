from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import get_session
from app.modules.lifecycle.schemas import IterationCreate, LifecycleRead
from app.modules.lifecycle.service import LifecycleService
from app.modules.settings.router import get_settings_service

router = APIRouter(tags=["lifecycle"])


def get_lifecycle_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> LifecycleService:
    settings = get_settings_service(request, session)

    def llm_available(project_id: str) -> bool:
        try:
            return settings.provider_for(settings.effective_llm_id(project_id)) is not None
        except NotFoundError:
            return False

    return LifecycleService(session, llm_available)


Service = Annotated[LifecycleService, Depends(get_lifecycle_service)]


@router.get("/projects/{project_id}/lifecycle", response_model=LifecycleRead)
def lifecycle(project_id: str, service: Service, iteration_id: str | None = None) -> LifecycleRead:
    """Iterations of the project and the stage statuses of one iteration (default: the active one).

    The active iteration is evaluated from the project's records; closed iterations return the
    statuses frozen when they ended.
    """
    return service.lifecycle(project_id, iteration_id)


@router.post("/projects/{project_id}/iterations", response_model=LifecycleRead, status_code=status.HTTP_201_CREATED)
def start_iteration(project_id: str, data: IterationCreate, service: Service) -> LifecycleRead:
    """Close the active iteration (freezing its statuses) and start a new one at ``start_stage``,
    reusing the latest outputs of the stages before it."""
    return service.start_iteration(project_id, data)
