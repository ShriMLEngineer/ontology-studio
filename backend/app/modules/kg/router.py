from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.kg.feedback import KgFeedbackService
from app.modules.kg.orchestrator import execute_kg_build
from app.modules.kg.policy import DEFAULT_POLICY_ID, POLICIES
from app.modules.kg.queries import KgQueryService
from app.modules.kg.schemas import (
    ValidationPolicyRead,
    BuildComparison,
    BuildCreate,
    BuildDetail,
    BuildLogRead,
    BuildStart,
    BuildSummary,
    BuildUpdate,
    EntityDetail,
    EntitySummary,
    EvaluationRead,
    FactDetail,
    FactPage,
    GapProposalRequest,
    GapProposalResult,
    GapRead,
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
)
from app.modules.kg.service import KgService
from app.modules.llm.provider import LLMProvider
from app.modules.llm.service import get_llm_provider

router = APIRouter(tags=["knowledge-graph"])


def get_kg_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> KgService:
    return KgService(session, max_records=request.app.state.settings.kg_max_records_per_source)


def get_query_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> KgQueryService:
    return KgQueryService(session, request.app.state.graph_store_factory)


Service = Annotated[KgService, Depends(get_kg_service)]
Queries = Annotated[KgQueryService, Depends(get_query_service)]
Provider = Annotated[LLMProvider | None, Depends(get_llm_provider)]


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
    provider: Provider,
) -> BuildDetail:
    """Save a build configuration; with ``start`` it is also queued for execution."""
    build = service.create_build(project_id, data, provider)
    if data.start:
        build = service.start_build(build.id, data.requested_by, provider)
        _schedule(request, background, provider, build.id)
    return service.detail(build, provider)


@router.get("/kg/builds/{build_id}", response_model=BuildDetail)
def get_build(build_id: str, service: Service, provider: Provider) -> BuildDetail:
    return service.get_build(build_id, provider)


@router.patch("/kg/builds/{build_id}", response_model=BuildDetail)
def update_build(build_id: str, data: BuildUpdate, service: Service, provider: Provider) -> BuildDetail:
    return service.detail(service.update_build(build_id, data), provider)


@router.delete("/kg/builds/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_build(build_id: str, service: Service) -> Response:
    service.delete_build(build_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/kg/builds/{build_id}/start", response_model=BuildDetail, status_code=status.HTTP_202_ACCEPTED)
def start_build(
    build_id: str, data: BuildStart, request: Request, background: BackgroundTasks, service: Service, provider: Provider
) -> BuildDetail:
    """Queue a configured build. Poll the build until it is ``completed`` or ``failed``."""
    build = service.start_build(build_id, data.requested_by, provider)
    _schedule(request, background, provider, build.id)
    return service.detail(build, provider)


@router.post("/kg/builds/{build_id}/rebuild", response_model=BuildDetail, status_code=status.HTTP_201_CREATED)
def rebuild(
    build_id: str,
    data: RebuildRequest,
    request: Request,
    background: BackgroundTasks,
    service: Service,
    provider: Provider,
) -> BuildDetail:
    """Create a new build from an earlier one with another published version. The earlier build is untouched."""
    build = service.rebuild(build_id, data)
    if data.start:
        build = service.start_build(build.id, data.requested_by, provider)
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
    class_id: Annotated[list[str] | None, Query()] = None,
    predicate_id: Annotated[list[str] | None, Query()] = None,
    source_id: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> GraphRead:
    return queries.graph(build_id, class_ids=class_id, predicate_ids=predicate_id, source_ids=source_id, limit=limit)


@router.get("/kg/builds/{build_id}/graph/search", response_model=list[GraphNodeRead])
def search_graph(
    build_id: str, q: str, queries: Queries, class_id: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[GraphNodeRead]:
    return queries.search(build_id, q, class_id, limit)


@router.get("/kg/builds/{build_id}/graph/nodes/{vertex_id}/neighborhood", response_model=GraphRead)
def neighborhood(
    build_id: str, vertex_id: str, queries: Queries, depth: Annotated[int, Query(ge=1, le=3)] = 1
) -> GraphRead:
    return queries.neighborhood(build_id, vertex_id, depth)


@router.get("/kg/builds/{build_id}/graph/elements/{element_id}", response_model=GraphElementDetail)
def graph_element(build_id: str, element_id: str, queries: Queries) -> GraphElementDetail:
    """A node or relationship with its source provenance, evidence and validation outcome."""
    return queries.element(build_id, element_id)


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
