import logging

from sqlalchemy.orm import Session

from app.modules.activity.service import record_activity
from app.modules.ontology.schemas import DraftSaveRequest, OntologyCreate
from app.modules.ontology.service import OntologyService
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from app.modules.seed import supply_chain

logger = logging.getLogger(__name__)


def seed_demo_data(session: Session) -> bool:
    """Create the Supply Chain demo project on an empty database. Returns True if seeded.

    Seeding is idempotent: it only runs when no projects exist, so user changes (including
    deleting or editing the demo content) are never overwritten on restart.
    """
    if ProjectRepository(session).count() > 0:
        return False

    project = ProjectService(session).create_project(
        ProjectCreate(**supply_chain.PROJECT, initial_ontology=OntologyCreate(**supply_chain.ONTOLOGY))
    )
    ontology_service = OntologyService(session)
    ontology = ontology_service.list_ontologies(project.id)[0]
    ontology_service.save_draft(
        ontology.id,
        DraftSaveRequest.model_validate(
            {"base_revision": ontology.draft_revision, **supply_chain.draft_content()}
        ),
    )
    record_activity(
        session,
        project_id=project.id,
        ontology_id=ontology.id,
        event_type="seed.loaded",
        summary="Supply Chain demonstration ontology loaded",
    )
    session.commit()
    logger.info("Seeded Supply Chain demonstration project %s", project.id)
    return True
