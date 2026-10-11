from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    char_count: int
    chunk_count: int
    uploaded_by: str
    created_at: datetime


class SourceChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    page: int | None
    start_offset: int
    end_offset: int
    text: str


class SourceDocumentDetail(SourceDocumentRead):
    chunks: list[SourceChunkRead]
