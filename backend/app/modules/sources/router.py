from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import get_session
from app.modules.sources.schemas import SourceDocumentDetail, SourceDocumentRead
from app.modules.sources.service import SourceService

router = APIRouter(tags=["sources"])


def get_source_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> SourceService:
    settings: Settings = request.app.state.settings
    return SourceService(session, chunk_chars=settings.discovery_chunk_chars)


Service = Annotated[SourceService, Depends(get_source_service)]


class PayloadTooLargeError(DomainError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "DOCUMENT_TOO_LARGE"


@router.get("/projects/{project_id}/sources", response_model=list[SourceDocumentRead])
def list_sources(project_id: str, service: Service) -> list[SourceDocumentRead]:
    return service.list_documents(project_id)


@router.post(
    "/projects/{project_id}/sources",
    response_model=SourceDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    project_id: str,
    request: Request,
    file: UploadFile,
    service: Service,
    uploaded_by: Annotated[str, Form()] = "",
) -> SourceDocumentRead:
    limit = request.app.state.settings.source_max_upload_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise PayloadTooLargeError(
            f"Documents are limited to {limit // (1024 * 1024)} MB.", details={"limit_bytes": limit}
        )
    return service.upload(project_id, file.filename or "document", content, uploaded_by)


@router.get("/sources/{document_id}", response_model=SourceDocumentDetail)
def get_source(document_id: str, service: Service) -> SourceDocumentDetail:
    return service.get_document(document_id)


@router.delete("/sources/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(document_id: str, service: Service) -> Response:
    service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
