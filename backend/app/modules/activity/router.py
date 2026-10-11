from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.activity.schemas import ActivityRead
from app.modules.activity.service import ActivityService

router = APIRouter(tags=["activity"])


def get_activity_service(session: Annotated[Session, Depends(get_session)]) -> ActivityService:
    return ActivityService(session)


Service = Annotated[ActivityService, Depends(get_activity_service)]


@router.get("/projects/{project_id}/activity", response_model=list[ActivityRead])
def list_project_activity(
    project_id: str, service: Service, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> list[ActivityRead]:
    return service.list_for_project(project_id, limit)
