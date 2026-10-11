import hashlib
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, DomainError, NotFoundError
from app.modules.activity.service import record_activity
from app.modules.projects.repository import ProjectRepository
from app.modules.sources.chunking import chunk_text
from app.modules.sources.models import SourceChunk, SourceDocument
from app.modules.sources.parsing import SUPPORTED_EXTENSIONS, DocumentParseError, parser_for
from app.modules.sources.schemas import SourceChunkRead, SourceDocumentDetail, SourceDocumentRead


class UnsupportedMediaError(DomainError):
    status_code = 415
    code = "UNSUPPORTED_DOCUMENT_TYPE"


class SourceService:
    def __init__(self, session: Session, *, chunk_chars: int = 3000) -> None:
        self.session = session
        self.chunk_chars = chunk_chars

    def _require_project(self, project_id: str) -> None:
        if ProjectRepository(self.session).get(project_id) is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")

    def _require(self, document_id: str) -> SourceDocument:
        document = self.session.get(SourceDocument, document_id)
        if document is None:
            raise NotFoundError(f"Source document '{document_id}' was not found.", code="SOURCE_NOT_FOUND")
        return document

    def list_documents(self, project_id: str) -> list[SourceDocumentRead]:
        self._require_project(project_id)
        stmt = (
            select(SourceDocument)
            .where(SourceDocument.project_id == project_id)
            .order_by(SourceDocument.created_at.desc())
        )
        return [SourceDocumentRead.model_validate(d) for d in self.session.scalars(stmt)]

    def get_document(self, document_id: str) -> SourceDocumentDetail:
        document = self._require(document_id)
        return SourceDocumentDetail(
            **SourceDocumentRead.model_validate(document).model_dump(),
            chunks=[SourceChunkRead.model_validate(c) for c in self.chunks(document_id)],
        )

    def chunks(self, document_id: str) -> list[SourceChunk]:
        stmt = select(SourceChunk).where(SourceChunk.document_id == document_id).order_by(SourceChunk.chunk_index)
        return list(self.session.scalars(stmt))

    def upload(self, project_id: str, filename: str, content: bytes, uploaded_by: str = "") -> SourceDocumentRead:
        self._require_project(project_id)
        name = PurePath(filename or "document").name[:255]
        parser = parser_for(name)
        if parser is None:
            raise UnsupportedMediaError(
                f"'{name}' is not a supported document type. Supported: {', '.join(SUPPORTED_EXTENSIONS)}.",
                details={"supported_extensions": list(SUPPORTED_EXTENSIONS)},
            )
        if not content:
            raise BusinessRuleError("The uploaded file is empty.", code="EMPTY_DOCUMENT")
        digest = hashlib.sha256(content).hexdigest()
        existing = self.session.scalars(
            select(SourceDocument).where(SourceDocument.project_id == project_id, SourceDocument.sha256 == digest)
        ).first()
        if existing is not None:
            raise ConflictError(
                f"This content was already uploaded as '{existing.filename}'.",
                code="DOCUMENT_ALREADY_UPLOADED",
                details={"document_id": existing.id},
            )
        try:
            parsed = parser.parse(content, name)
        except DocumentParseError as error:
            raise BusinessRuleError(str(error), code="DOCUMENT_PARSE_FAILED") from error

        text_chunks = chunk_text(parsed.text, self.chunk_chars)
        document = SourceDocument(
            project_id=project_id,
            filename=name,
            media_type=parsed.media_type,
            size_bytes=len(content),
            sha256=digest,
            page_count=parsed.page_count,
            char_count=len(parsed.text),
            chunk_count=len(text_chunks),
            text=parsed.text,
            uploaded_by=uploaded_by.strip()[:200],
        )
        self.session.add(document)
        self.session.flush()
        for chunk in text_chunks:
            self.session.add(
                SourceChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    page=parsed.page_at(chunk.start),
                    start_offset=chunk.start,
                    end_offset=chunk.end,
                    text=chunk.text,
                )
            )
        record_activity(
            self.session,
            project_id=project_id,
            event_type="source.uploaded",
            summary=f"Source document '{name}' uploaded ({len(text_chunks)} chunks)",
            details={"document_id": document.id},
        )
        self.session.commit()
        return SourceDocumentRead.model_validate(document)

    def delete(self, document_id: str) -> None:
        document = self._require(document_id)
        record_activity(
            self.session,
            project_id=document.project_id,
            event_type="source.deleted",
            summary=f"Source document '{document.filename}' deleted (evidence quotes are retained)",
            details={"document_id": document.id},
        )
        self.session.delete(document)
        self.session.commit()
