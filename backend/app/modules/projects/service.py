from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.modules.activity.service import record_activity
from app.modules.ontology.repository import OntologyRepository
from app.modules.ontology.service import OntologyService
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectRead, ProjectUpdate


def _require_registered(session: Session, llm_config_id: str | None, graph_connection_id: str | None) -> None:
    from app.modules.settings.models import GraphConnection, LlmConfiguration

    if llm_config_id not in (None, "env-default") and session.get(LlmConfiguration, llm_config_id) is None:
        raise NotFoundError(f"LLM configuration '{llm_config_id}' was not found.", code="LLM_CONFIG_NOT_FOUND")
    if graph_connection_id not in (None, "local-sql", "oxigraph-embedded") and session.get(
        GraphConnection, graph_connection_id
    ) is None:
        raise NotFoundError(f"Graph connection '{graph_connection_id}' was not found.", code="GRAPH_CONNECTION_NOT_FOUND")


class ProjectService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.ontologies = OntologyRepository(session)

    def _to_read(self, project: Project, ontology_count: int | None = None) -> ProjectRead:
        if ontology_count is None:
            ontology_count = self.ontologies.count_by_project().get(project.id, 0)
        return ProjectRead(
            id=project.id,
            name=project.name,
            description=project.description,
            business_domain=project.business_domain,
            ontology_count=ontology_count,
            default_llm_config_id=project.default_llm_config_id or "env-default",
            default_graph_connection_id=project.default_graph_connection_id or "local-sql",
            data_namespace=project.data_namespace,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    def _require(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")
        return project

    def list_projects(self) -> list[ProjectRead]:
        counts = self.ontologies.count_by_project()
        return [self._to_read(p, counts.get(p.id, 0)) for p in self.projects.list()]

    def get_project(self, project_id: str) -> ProjectRead:
        return self._to_read(self._require(project_id))

    def create_project(self, data: ProjectCreate) -> ProjectRead:
        if self.projects.find_by_name(data.name):
            raise ConflictError(
                f"A project named '{data.name}' already exists.", code="PROJECT_NAME_TAKEN"
            )
        _require_registered(self.session, data.default_llm_config_id, data.default_graph_connection_id)
        project = self.projects.add(
            Project(
                name=data.name,
                description=data.description,
                business_domain=data.business_domain,
                default_llm_config_id=None if data.default_llm_config_id in (None, "env-default") else data.default_llm_config_id,
                default_graph_connection_id=None
                if data.default_graph_connection_id in (None, "local-sql")
                else data.default_graph_connection_id,
            )
        )
        record_activity(
            self.session,
            project_id=project.id,
            event_type="project.created",
            summary=f"Project '{project.name}' created",
        )
        if data.initial_ontology is not None:
            OntologyService(self.session).create_ontology(
                project.id, data.initial_ontology, commit=False
            )
        self.session.commit()
        return self._to_read(project)

    def update_project(self, project_id: str, data: ProjectUpdate) -> ProjectRead:
        project = self._require(project_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        new_name = changes.get("name")
        if new_name and new_name.lower() != project.name.lower():
            existing = self.projects.find_by_name(new_name)
            if existing is not None and existing.id != project.id:
                raise ConflictError(
                    f"A project named '{new_name}' already exists.", code="PROJECT_NAME_TAKEN"
                )
        changed = {k: v for k, v in changes.items() if getattr(project, k) != v}
        if changed:
            for key, value in changed.items():
                setattr(project, key, value)
            record_activity(
                self.session,
                project_id=project.id,
                event_type="project.updated",
                summary=f"Project details updated ({', '.join(sorted(changed))})",
            )
            self.session.commit()
        return self._to_read(project)
