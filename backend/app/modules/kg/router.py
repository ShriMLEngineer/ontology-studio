from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import get_session
from app.modules.graph.sparql import SparqlResult
from app.modules.kg.deployments import KgDeploymentService
from app.modules.kg.feedback import KgFeedbackService
from app.modules.kg.models import KgBuild
from app.modules.kg.orchestrator import execute_kg_build
from app.modules.kg.policy import DEFAULT_POLICY_ID, POLICIES
from app.modules.kg.queries import GraphSource, KgQueryService
from app.modules.kg.schemas import (
    BuildSettings,
    ValidationPolicyRead,
    BuildComparison,
    BuildCreate,
    BuildDetail,
    BuildLogRead,
    BuildStart,
    BuildSummary,
    BuildUpdate,
    CompatibilityRead,
    DeploymentCreate,
    DeploymentRead,
    EntityDetail,
    EntitySummary,
    EvaluationRead,
    FactDetail,
    FactPage,
    GapProposalRequest,
    GapProposalResult,
    GapRead,
    GraphCapabilitiesRead,
    GraphElementDetail,
    GraphNodeRead,
    GraphRead,
    MappingCreate,
    MappingRead,
    MappingSuggestion,
    MappingUpdate,
    MappingValidateRequest,
    MappingValidation,
    PublishedVersionOption,
    RebuildRequest,
    SourcePreview,
    SparqlQueryRequest,
)
from app.modules.kg.service import KgService
from app.modules.llm.provider import LLMProvider
from app.modules.llm.service import get_llm_provider
from app.modules.settings.router import get_settings_service
from app.modules.settings.service import SettingsService

router = APIRouter(tags=["knowledge-graph"])


def get_kg_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> KgService:
    return KgService(session, max_records=request.app.state.settings.kg_max_records_per_source)


def get_query_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> KgQueryService:
    return KgQueryService(session, request.app.state.graph_store_factory)


Service = Annotated[KgService, Depends(get_kg_service)]
Queries = Annotated[KgQueryService, Depends(get_query_service)]
Provider = Annotated[LLMProvider | None, Depends(get_llm_provider)]


class BuildResources:
    """Resolves the LLM and graph target of a build: build setting -> project default -> built-in."""

    def __init__(self, settings_service: SettingsService) -> None:
        self.settings = settings_service

    def validate(self, settings: BuildSettings | None) -> None:
        if settings is not None:
            self.settings.require_llm_id(settings.llm_config_id)
            self.settings.require_graph_id(settings.graph_connection_id)

    def provider(self, build: KgBuild) -> LLMProvider | None:
        config_id = self.settings.effective_kg_llm_id(build.project_id, (build.settings or {}).get("llm_config_id"))
        try:
            return self.settings.provider_for(config_id)
        except NotFoundError:
            return None  # deleted configuration: readiness reports that no LLM is available

    def selection(self, build: KgBuild) -> dict[str, Any]:
        llm_id = self.settings.effective_kg_llm_id(build.project_id, (build.settings or {}).get("llm_config_id"))
        graph_id = self.settings.effective_graph_id(build.project_id, (build.settings or {}).get("graph_connection_id"))
        graph = self.settings.get_graph(graph_id)
        return {
            "llm_config_id": llm_id,
            "llm_configuration": self.settings.llm_snapshot(llm_id),
            "graph_target": {
                "id": graph.id,
                "name": graph.name,
                "kind": graph.kind,
                "provider": graph.provider,
                "model": graph.model,
                "config": graph.config,
                "secret_env": graph.secret_env,
            },
        }


def get_build_resources(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> BuildResources:
    return BuildResources(get_settings_service(request, session))


Resources = Annotated[BuildResources, Depends(get_build_resources)]


def get_deployment_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> KgDeploymentService:
    return KgDeploymentService(
        session,
        request.app.state.settings,
        get_settings_service(request, session),
        request.app.state.graph_store_factory(session),
    )


Deployments = Annotated[KgDeploymentService, Depends(get_deployment_service)]


def _source(deployments: KgDeploymentService, build_id: str, deployment_id: str | None) -> GraphSource | None:
    if not deployment_id:
        return None
    store, warnings = deployments.reader(build_id, deployment_id)
    row = deployments.get(deployment_id)
    return GraphSource(store=store, deployment_id=deployment_id, label=row.target_kind, warnings=warnings)


def _schedule(request: Request, background: BackgroundTasks, provider: LLMProvider | None, build_id: str) -> None:
    background.add_task(
        execute_kg_build,
        request.app.state.session_factory,
        provider,
        request.app.state.settings,
        request.app.state.graph_store_factory,
        build_id,
    )


# ---------------------------------------------------------------------- sources, versions, mappings


@router.get("/sources/{document_id}/preview", response_model=SourcePreview)
def preview_source(document_id: str, service: Service, rows: Annotated[int, Query(ge=1, le=200)] = 20) -> SourcePreview:
    return service.preview(document_id, rows)


@router.get("/kg/validation-policies", response_model=list[ValidationPolicyRead])
def list_validation_policies() -> list[ValidationPolicyRead]:
    """Immutable, versioned validation policies; builds record the full policy they ran with."""
    return [
        ValidationPolicyRead(**policy.config(), default=policy.id == DEFAULT_POLICY_ID)  # type: ignore[arg-type]
        for policy in POLICIES.values()
    ]


@router.get("/projects/{project_id}/kg/ontology-versions", response_model=list[PublishedVersionOption])
def published_versions(project_id: str, service: Service) -> list[PublishedVersionOption]:
    """Published (immutable) ontology versions selectable for a KG build. Drafts are never listed."""
    return service.list_published_versions(project_id)


@router.get("/projects/{project_id}/kg/mappings", response_model=list[MappingRead])
def list_mappings(project_id: str, service: Service, document_id: str | None = None) -> list[MappingRead]:
    return service.list_mappings(project_id, document_id)


@router.post("/projects/{project_id}/kg/mappings", response_model=MappingRead, status_code=status.HTTP_201_CREATED)
def create_mapping(project_id: str, data: MappingCreate, service: Service) -> MappingRead:
    return service.create_mapping(project_id, data)


@router.post("/projects/{project_id}/kg/mappings/validate", response_model=MappingValidation)
def validate_mapping(project_id: str, data: MappingValidateRequest, service: Service) -> MappingValidation:
    return service.validate_mapping(project_id, data)


@router.get("/sources/{document_id}/mapping-suggestion", response_model=MappingSuggestion)
def suggest_mapping(document_id: str, ontology_version_id: str, service: Service) -> MappingSuggestion:
    return service.suggest(document_id, ontology_version_id)


@router.get("/kg/mappings/{mapping_id}", response_model=MappingRead)
def get_mapping(mapping_id: str, service: Service) -> MappingRead:
    return service.get_mapping(mapping_id)


@router.put("/kg/mappings/{mapping_id}", response_model=MappingRead)
def update_mapping(mapping_id: str, data: MappingUpdate, service: Service) -> MappingRead:
    return service.update_mapping(mapping_id, data)


@router.delete("/kg/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(mapping_id: str, service: Service) -> Response:
    service.delete_mapping(mapping_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------- builds


@router.get("/projects/{project_id}/kg/builds", response_model=list[BuildSummary])
def list_builds(project_id: str, service: Service) -> list[BuildSummary]:
    return service.list_builds(project_id)


@router.post("/projects/{project_id}/kg/builds", response_model=BuildDetail, status_code=status.HTTP_201_CREATED)
def create_build(
    project_id: str,
    data: BuildCreate,
    request: Request,
    background: BackgroundTasks,
    service: Service,
    resources: Resources,
) -> BuildDetail:
    """Save a build configuration; with ``start`` it is also queued for execution."""
    resources.validate(data.settings)
    build = service.create_build(project_id, data, None)
    provider = resources.provider(build)
    if data.start:
        build = service.start_build(build.id, data.requested_by, provider, resources.selection(build))
        _schedule(request, background, provider, build.id)
    return service.detail(build, provider)


@router.get("/kg/builds/{build_id}", response_model=BuildDetail)
def get_build(build_id: str, service: Service, resources: Resources) -> BuildDetail:
    build = service.require_build(build_id)
    return service.detail(build, resources.provider(build))


@router.patch("/kg/builds/{build_id}", response_model=BuildDetail)
def update_build(build_id: str, data: BuildUpdate, service: Service, resources: Resources) -> BuildDetail:
    resources.validate(data.settings)
    build = service.update_build(build_id, data)
    return service.detail(build, resources.provider(build))


@router.delete("/kg/builds/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_build(build_id: str, service: Service) -> Response:
    service.delete_build(build_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/kg/builds/{build_id}/start", response_model=BuildDetail, status_code=status.HTTP_202_ACCEPTED)
def start_build(
    build_id: str, data: BuildStart, request: Request, background: BackgroundTasks, service: Service, resources: Resources
) -> BuildDetail:
    """Queue a configured build. Poll the build until it is ``completed`` or ``failed``."""
    build = service.require_build(build_id)
    provider = resources.provider(build)
    build = service.start_build(build_id, data.requested_by, provider, resources.selection(build))
    _schedule(request, background, provider, build.id)
    return service.detail(build, provider)


@router.post("/kg/builds/{build_id}/rebuild", response_model=BuildDetail, status_code=status.HTTP_201_CREATED)
def rebuild(
    build_id: str,
    data: RebuildRequest,
    request: Request,
    background: BackgroundTasks,
    service: Service,
    resources: Resources,
) -> BuildDetail:
    """Create a new build from an earlier one with another published version. The earlier build is untouched."""
    build = service.rebuild(build_id, data)
    provider = resources.provider(build)
    if data.start:
        build = service.start_build(build.id, data.requested_by, provider, resources.selection(build))
        _schedule(request, background, provider, build.id)
    return service.detail(build, provider)


@router.get("/kg/builds/{build_id}/logs", response_model=list[BuildLogRead])
def build_logs(build_id: str, service: Service, after: int = 0) -> list[BuildLogRead]:
    """Execution log lines; pass ``after`` (last seen id) to fetch only new lines."""
    return service.list_logs(build_id, after)


@router.get("/kg/compare", response_model=BuildComparison)
def compare_builds(base: str, target: str, queries: Queries) -> BuildComparison:
    return queries.compare(base, target)


# ---------------------------------------------------------------------- facts & entities


@router.get("/kg/builds/{build_id}/facts", response_model=FactPage)
def list_facts(
    build_id: str,
    queries: Queries,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    kind: str | None = None,
    source_id: str | None = None,
    predicate_id: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> FactPage:
    return queries.list_facts(
        build_id, status=status_filter, kind=kind, source_id=source_id, predicate_id=predicate_id, query=q, limit=limit
    )


@router.get("/kg/facts/{fact_id}", response_model=FactDetail)
def get_fact(fact_id: str, queries: Queries) -> FactDetail:
    return queries.get_fact(fact_id)


@router.get("/kg/builds/{build_id}/entities", response_model=list[EntitySummary])
def list_entities(build_id: str, queries: Queries, q: str | None = None, method: str | None = None) -> list[EntitySummary]:
    return queries.list_entities(build_id, query=q, method=method)


@router.get("/kg/entities/{entity_id}", response_model=EntityDetail)
def get_entity(entity_id: str, queries: Queries) -> EntityDetail:
    return queries.get_entity(entity_id)


# ---------------------------------------------------------------------- graph


@router.get("/kg/builds/{build_id}/graph", response_model=GraphRead)
def build_graph(
    build_id: str,
    queries: Queries,
    deployments: Deployments,
    class_id: Annotated[list[str] | None, Query()] = None,
    predicate_id: Annotated[list[str] | None, Query()] = None,
    source_id: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    deployment_id: str | None = None,
) -> GraphRead:
    """The build's graph; with ``deployment_id`` it is read back from that deployment's target."""
    return queries.graph(
        build_id,
        class_ids=class_id,
        predicate_ids=predicate_id,
        source_ids=source_id,
        limit=limit,
        via=_source(deployments, build_id, deployment_id),
    )


@router.get("/kg/builds/{build_id}/graph/search", response_model=list[GraphNodeRead])
def search_graph(
    build_id: str,
    q: str,
    queries: Queries,
    deployments: Deployments,
    class_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    deployment_id: str | None = None,
) -> list[GraphNodeRead]:
    return queries.search(build_id, q, class_id, limit, via=_source(deployments, build_id, deployment_id))


@router.get("/kg/builds/{build_id}/graph/nodes/{vertex_id}/neighborhood", response_model=GraphRead)
def neighborhood(
    build_id: str,
    vertex_id: str,
    queries: Queries,
    deployments: Deployments,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    deployment_id: str | None = None,
) -> GraphRead:
    return queries.neighborhood(build_id, vertex_id, depth, via=_source(deployments, build_id, deployment_id))


@router.get("/kg/builds/{build_id}/graph/elements/{element_id}", response_model=GraphElementDetail)
def graph_element(
    build_id: str, element_id: str, queries: Queries, deployments: Deployments, deployment_id: str | None = None
) -> GraphElementDetail:
    """A node or relationship with its source provenance, evidence and validation outcome."""
    return queries.element(build_id, element_id, via=_source(deployments, build_id, deployment_id))


# ---------------------------------------------------------------------- graph deployments

@router.get("/kg/graph-capabilities", response_model=GraphCapabilitiesRead)
def graph_capabilities(deployments: Deployments) -> GraphCapabilitiesRead:
    """Versioned capability profiles of graph targets and the available mapping profiles."""
    return deployments.capabilities()


@router.get("/kg/builds/{build_id}/compatibility", response_model=CompatibilityRead)
def compatibility(
    build_id: str,
    deployments: Deployments,
    target_id: str | None = None,
    kind: str | None = None,
    mapping_profile: str | None = None,
) -> CompatibilityRead:
    """What a target (registered connection or bare kind) preserves of this build and its ontology version."""
    return deployments.compatibility(build_id, target_id=target_id, kind=kind, mapping_profile=mapping_profile)


@router.get("/kg/builds/{build_id}/deployments", response_model=list[DeploymentRead])
def list_deployments(build_id: str, deployments: Deployments) -> list[DeploymentRead]:
    return deployments.list_for_build(build_id)


@router.post("/kg/builds/{build_id}/deployments", response_model=DeploymentRead, status_code=status.HTTP_201_CREATED)
def create_deployment(build_id: str, data: DeploymentCreate, deployments: Deployments) -> DeploymentRead:
    """Deploy a completed build to a graph target and verify it. A failing target is recorded as a failed deployment."""
    return deployments.create(build_id, data)


@router.get("/kg/deployments/{deployment_id}", response_model=DeploymentRead)
def get_deployment(deployment_id: str, deployments: Deployments) -> DeploymentRead:
    return deployments.get(deployment_id)


@router.post("/kg/deployments/{deployment_id}/query", response_model=SparqlResult)
def query_deployment(deployment_id: str, data: SparqlQueryRequest, deployments: Deployments) -> SparqlResult:
    """Read-only SPARQL (SELECT, ASK, CONSTRUCT, DESCRIBE) over the deployment's graphs; updates and SERVICE are rejected."""
    return deployments.query(deployment_id, data)


# ---------------------------------------------------------------------- evaluation & feedback


@router.get("/kg/builds/{build_id}/evaluation", response_model=EvaluationRead)
def evaluation(build_id: str, queries: Queries) -> EvaluationRead:
    return queries.evaluation(build_id)


@router.get("/kg/builds/{build_id}/gaps", response_model=list[GapRead])
def gaps(build_id: str, queries: Queries) -> list[GapRead]:
    return queries.gaps(build_id)


@router.post(
    "/kg/builds/{build_id}/gaps/proposals", response_model=GapProposalResult, status_code=status.HTTP_201_CREATED
)
def propose_gaps(
    build_id: str, data: GapProposalRequest, session: Annotated[Session, Depends(get_session)]
) -> GapProposalResult:
    """Create pending ontology change proposals for SME review. Nothing is applied or published."""
    return KgFeedbackService(session).create_proposals(build_id, data)
