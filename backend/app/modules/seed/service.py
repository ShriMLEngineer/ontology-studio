import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.modules.activity.service import record_activity
from app.modules.ontology.schemas import DraftSaveRequest, OntologyCreate
from app.modules.ontology.service import OntologyService
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from app.modules.seed import supply_chain
from app.modules.sources.service import SourceService

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


SAMPLE_EXTENSIONS = (".csv", ".pdf")


def seed_sample_sources(session: Session, samples_dir: Path, project_name: str = supply_chain.PROJECT["name"]) -> list[str]:
    """Upload the demonstration source files into the demo project (skipping ones already present).

    Uses the regular upload service, so samples are parsed and chunked exactly like user uploads.
    """
    project = next((p for p in ProjectService(session).list_projects() if p.name == project_name), None)
    if project is None:
        raise ValueError(f"Project '{project_name}' does not exist; run the 'seed' command first.")
    uploaded: list[str] = []
    service = SourceService(session)
    for path in sorted(samples_dir.iterdir()):
        if path.suffix.lower() not in SAMPLE_EXTENSIONS:
            continue
        try:
            service.upload(project.id, path.name, path.read_bytes(), uploaded_by="sample loader")
        except ConflictError:
            continue
        uploaded.append(path.name)
    return uploaded
