from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.registry.diff import SchemaDiff
from app.modules.registry.schemas import PublishPreview, PublishRequest, VersionDetail, VersionSummary
from app.modules.registry.service import RegistryService

router = APIRouter(prefix="/ontologies/{ontology_id}", tags=["registry"])


def get_registry_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> RegistryService:
    return RegistryService(session, request.app.state.artifact_repository)


Service = Annotated[RegistryService, Depends(get_registry_service)]


@router.get("/versions", response_model=list[VersionSummary])
def list_versions(ontology_id: str, service: Service) -> list[VersionSummary]:
    return service.list_versions(ontology_id)


@router.get("/publish-preview", response_model=PublishPreview)
def publish_preview(
    ontology_id: str, service: Service, bump: Literal["major", "minor", "patch"] | None = None
) -> PublishPreview:
    return service.preview(ontology_id, bump)


@router.post("/versions", response_model=VersionDetail, status_code=status.HTTP_201_CREATED)
def publish_version(ontology_id: str, data: PublishRequest, service: Service) -> VersionDetail:
    """Publish the current draft as an immutable version (blocked by validation errors)."""
    return service.publish(ontology_id, data)


@router.get("/versions/{version_id}", response_model=VersionDetail)
def get_version(ontology_id: str, version_id: str, service: Service) -> VersionDetail:
    return service.get_version(ontology_id, version_id)


@router.get("/versions/{version_id}/export", response_class=Response)
def export_version(
    ontology_id: str,
    version_id: str,
    service: Service,
    fmt: Annotated[Literal["turtle", "json"], Query(alias="format")] = "turtle",
) -> Response:
    content, artifact = service.export(ontology_id, version_id, fmt)
    return Response(
        content=content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-SHA256": artifact.sha256,
        },
    )


@router.get("/compare", response_model=SchemaDiff)
def compare(
    ontology_id: str,
    service: Service,
    base: Annotated[str, Query(description="Version id or 'draft'")],
    target: Annotated[str, Query(description="Version id or 'draft'")] = "draft",
) -> SchemaDiff:
    return service.compare(ontology_id, base, target)
