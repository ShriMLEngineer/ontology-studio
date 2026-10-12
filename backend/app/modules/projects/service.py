from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.secrets import secret_is_set
from app.modules.activity.service import record_activity
from app.modules.ontology.repository import OntologyRepository
from app.modules.ontology.service import OntologyService
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectRead, ProjectUpdate


def _require_registered(
    session: Session, llm_config_ids: list[str | None], graph_connection_id: str | None
) -> None:
    from app.modules.settings.models import GraphConnection, LlmConfiguration

    for llm_config_id in llm_config_ids:
        if llm_config_id in (None, "env-default"):
            continue
        llm = session.get(LlmConfiguration, llm_config_id)
        if llm is None:
            raise NotFoundError(f"LLM configuration '{llm_config_id}' was not found.", code="LLM_CONFIG_NOT_FOUND")
        if not llm.enabled:
            raise ConflictError(f"LLM configuration '{llm.name}' is deactivated.", code="LLM_CONFIG_DISABLED")
        key_required = llm.provider in {"openai", "anthropic"} or (
            llm.provider == "azure-foundry"
            and (llm.provider_config or {}).get("auth_method", "api_key") == "api_key"
        )
        if key_required and not secret_is_set(llm.api_key_env):
            raise ConflictError(
                f"Configure environment variable {llm.api_key_env or '(credential reference required)'} "
                "before selecting this LLM.",
                code="LLM_CREDENTIAL_MISSING",
            )
    if graph_connection_id not in (None, "local-sql", "oxigraph-embedded"):
        graph = session.get(GraphConnection, graph_connection_id)
        if graph is None:
            raise NotFoundError(
                f"Graph connection '{graph_connection_id}' was not found.", code="GRAPH_CONNECTION_NOT_FOUND"
            )
        if not graph.enabled:
            raise ConflictError(
                f"Graph database '{graph.name}' is disabled. Enable it in Settings first.",
                code="GRAPH_CONNECTION_DISABLED",
            )


def _workspace_default_graph(session: Session) -> str | None:
    """The registered graph database preselected for new projects (existing projects are never changed)."""
    from sqlalchemy import select

    from app.modules.settings.models import GraphConnection

    return session.scalars(
        select(GraphConnection.id).where(GraphConnection.is_default.is_(True), GraphConnection.enabled.is_(True))
    ).first()


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
            default_llm_config_id=(
                project.default_discovery_llm_config_id or project.default_llm_config_id or "env-default"
            ),
            default_discovery_llm_config_id=(
                project.default_discovery_llm_config_id or project.default_llm_config_id or "env-default"
            ),
            default_kg_llm_config_id=project.default_kg_llm_config_id or project.default_llm_config_id or "env-default",
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
        discovery_llm = data.default_discovery_llm_config_id or data.default_llm_config_id
        kg_llm = data.default_kg_llm_config_id or data.default_llm_config_id
        graph_id = data.default_graph_connection_id or _workspace_default_graph(self.session)
        _require_registered(
            self.session,
            [data.default_llm_config_id, discovery_llm, kg_llm],
            graph_id,
        )
        project = self.projects.add(
            Project(
                name=data.name,
                description=data.description,
                business_domain=data.business_domain,
                default_llm_config_id=None if data.default_llm_config_id in (None, "env-default") else data.default_llm_config_id,
                default_discovery_llm_config_id=(
                    None if discovery_llm in (None, "env-default") else discovery_llm
                ),
                default_kg_llm_config_id=None if kg_llm in (None, "env-default") else kg_llm,
                default_graph_connection_id=None
                if graph_id in (None, "local-sql")
                else graph_id,
            )
        )
        record_activity(
            self.session,
            project_id=project.id,
            event_type="project.created",
            summary=f"Project '{project.name}' created",
        )
        from app.modules.lifecycle.service import LifecycleService

        LifecycleService(self.session).ensure_first_iteration(project)
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
