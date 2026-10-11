from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.ontology.domain import NodeShape
from app.modules.semantics.graphs import RdfFormat
from app.modules.semantics.router import MAX_RDF_UPLOAD_BYTES, RdfTooLargeError
from app.modules.shacl.model import NodeShapeInput
from app.modules.shacl.schemas import (
    SampleValidationRequest,
    ShaclValidationResponse,
    ShapesImportResponse,
    ShapesOverview,
)
from app.modules.shacl.service import ShapeService

router = APIRouter(prefix="/ontologies/{ontology_id}/shapes", tags=["shacl"])


def get_shape_service(session: Annotated[Session, Depends(get_session)]) -> ShapeService:
    return ShapeService(session)


Service = Annotated[ShapeService, Depends(get_shape_service)]
Actor = Annotated[str, Query(max_length=200)]


@router.get("", response_model=ShapesOverview)
def overview(ontology_id: str, service: Service) -> ShapesOverview:
    """Authored, generated (constraint and signature) and preserved shapes of the draft, with a
    SHACL-SHACL well-formedness check of the complete shapes graph."""
    return service.overview(ontology_id)


@router.post("", response_model=NodeShape, status_code=status.HTTP_201_CREATED)
def create_shape(ontology_id: str, data: NodeShapeInput, service: Service, actor: Actor = "") -> NodeShape:
    return service.create(ontology_id, data, actor)


@router.put("/{shape_id}", response_model=NodeShape)
def update_shape(ontology_id: str, shape_id: str, data: NodeShapeInput, service: Service, actor: Actor = "") -> NodeShape:
    return service.update(ontology_id, shape_id, data, actor)


@router.delete("/{shape_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shape(ontology_id: str, shape_id: str, service: Service, actor: Actor = "") -> Response:
    service.delete(ontology_id, shape_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/rdf", response_class=Response)
def export_shapes(
    ontology_id: str,
    service: Service,
    fmt: Annotated[RdfFormat, Query(alias="format")] = "turtle",
    download: bool = False,
) -> Response:
    content, info, filename = service.export(ontology_id, fmt)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
    return Response(content=content, media_type=info.media_type, headers=headers)


@router.post("/validate", response_model=ShaclValidationResponse)
def validate_sample(ontology_id: str, data: SampleValidationRequest, service: Service) -> ShaclValidationResponse:
    """Validate sample instance data against the draft's shapes (no inference; ontology hierarchy mixed in)."""
    return service.validate_sample(ontology_id, data)


@router.post("/import", response_model=ShapesImportResponse, status_code=status.HTTP_201_CREATED)
async def import_shapes(
    ontology_id: str,
    file: UploadFile,
    service: Service,
    rdf_format: Annotated[RdfFormat | None, Form()] = None,
    imported_by: Annotated[str, Form()] = "",
) -> ShapesImportResponse:
    content = await file.read(MAX_RDF_UPLOAD_BYTES + 1)
    if len(content) > MAX_RDF_UPLOAD_BYTES:
        raise RdfTooLargeError(f"RDF documents are limited to {MAX_RDF_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return service.import_shapes(
        ontology_id, filename=file.filename or "shapes.ttl", data=content, rdf_format=rdf_format, actor=imported_by
    )
