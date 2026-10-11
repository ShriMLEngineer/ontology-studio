from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.projects.models import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    def list(self) -> list[Project]:
        return list(self.session.scalars(select(Project).order_by(Project.created_at, Project.name)))

    def find_by_name(self, name: str) -> Project | None:
        stmt = select(Project).where(func.lower(Project.name) == name.lower())
        return self.session.scalars(stmt).first()

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Project)) or 0

    def add(self, project: Project) -> Project:
        self.session.add(project)
        self.session.flush()
        return project
