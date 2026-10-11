from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.activity.models import ActivityEvent
from app.modules.activity.schemas import ActivityRead
from app.modules.projects.repository import ProjectRepository


def record_activity(
    session: Session,
    *,
    project_id: str,
    event_type: str,
    summary: str,
    ontology_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Stage an audit event in the caller's unit of work (the caller commits)."""
    event = ActivityEvent(
        project_id=project_id,
        ontology_id=ontology_id,
        event_type=event_type,
        summary=summary[:500],
        details=details or {},
    )
    session.add(event)
    return event


class ActivityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_project(self, project_id: str, limit: int = 20) -> list[ActivityRead]:
        if ProjectRepository(self.session).get(project_id) is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")
        stmt = (
            select(ActivityEvent)
            .where(ActivityEvent.project_id == project_id)
            .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id)
            .limit(limit)
        )
        return [ActivityRead.model_validate(e) for e in self.session.scalars(stmt)]
