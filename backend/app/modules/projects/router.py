from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.projects.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.modules.projects.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_service(session: Annotated[Session, Depends(get_session)]) -> ProjectService:
    return ProjectService(session)


Service = Annotated[ProjectService, Depends(get_project_service)]


@router.get("", response_model=list[ProjectRead])
def list_projects(service: Service) -> list[ProjectRead]:
    return service.list_projects()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, service: Service) -> ProjectRead:
    return service.create_project(data)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, service: Service) -> ProjectRead:
    return service.get_project(project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, data: ProjectUpdate, service: Service) -> ProjectRead:
    return service.update_project(project_id, data)
