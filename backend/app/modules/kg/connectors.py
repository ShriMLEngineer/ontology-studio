"""Source connectors: the boundary between the KG pipeline and where source data lives.

The pipeline consumes two interfaces only:

* :class:`StructuredSource` - named columns and records (CSV today; a Snowflake table or query
  connector implements the same interface later without changing mapping or pipeline code).
* :class:`TextSource` - page-aware text chunks for ontology-guided LLM extraction (PDF, text).

Both are created from the existing Phase 2 source documents; no ingestion is duplicated.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.sources.models import SourceChunk, SourceDocument

TABLE_MEDIA_TYPES = {"text/csv": ",", "text/tab-separated-values": "\t"}


class SourceReadError(ValueError):
    pass


@dataclass(frozen=True)
class TableRecord:
    row_number: int  # 1-based data row number (header excluded)
    line_number: int  # 1-based line in the file where the record starts
    values: dict[str, str]
    raw: str  # the exact source text of the record
    chunk_id: str | None


@dataclass(frozen=True)
class TextChunk:
    id: str
    index: int
    page: int | None
    start_offset: int
    text: str


class StructuredSource(Protocol):
    source_id: str
    source_name: str

    def columns(self) -> list[str]: ...

    def records(self, limit: int | None = None) -> Iterator[TableRecord]: ...

    def count(self) -> int: ...


class TextSource(Protocol):
    source_id: str
    source_name: str

    def chunks(self) -> list[TextChunk]: ...


def is_structured(document: SourceDocument) -> bool:
    return document.media_type in TABLE_MEDIA_TYPES


def _clean_headers(raw: list[str]) -> list[str]:
    headers: list[str] = []
    for index, value in enumerate(raw, start=1):
        name = value.strip().lstrip("\ufeff") or f"column_{index}"
        base, counter = name, 2
        while name in headers:
            name, counter = f"{base}_{counter}", counter + 1
        headers.append(name)
    return headers


class CsvDocumentSource:
    """Structured records parsed from an uploaded CSV/TSV source document."""

    def __init__(self, session: Session, document: SourceDocument) -> None:
        if not is_structured(document):
            raise SourceReadError(f"'{document.filename}' is not a structured (CSV/TSV) source.")
        self.source_id = document.id
        self.source_name = document.filename
        self._text = document.text
        self._delimiter = TABLE_MEDIA_TYPES[document.media_type]
        self._chunks = [
            (c.id, c.start_offset, c.end_offset)
            for c in session.scalars(
                select(SourceChunk).where(SourceChunk.document_id == document.id).order_by(SourceChunk.chunk_index)
            )
        ]
        lines = self._text.split("\n")
        self._lines = lines
        self._line_offsets: list[int] = []
        offset = 0
        for line in lines:
            self._line_offsets.append(offset)
            offset += len(line) + 1
        reader = csv.reader(io.StringIO(self._text), delimiter=self._delimiter)
        try:
            header = next(reader)
        except StopIteration as error:
            raise SourceReadError(f"'{document.filename}' has no header row.") from error
        self._columns = _clean_headers(header)

    def columns(self) -> list[str]:
        return list(self._columns)

    def _chunk_at(self, offset: int) -> str | None:
        for chunk_id, start, end in self._chunks:
            if start <= offset < end:
                return chunk_id
        return self._chunks[-1][0] if self._chunks else None

    def records(self, limit: int | None = None) -> Iterator[TableRecord]:
        reader = csv.reader(io.StringIO(self._text), delimiter=self._delimiter)
        next(reader, None)
        previous_line = reader.line_num
        row_number = 0
        for row in reader:
            start_line, end_line = previous_line + 1, reader.line_num
            previous_line = reader.line_num
            if not any(cell.strip() for cell in row):
                continue
            row_number += 1
            if limit is not None and row_number > limit:
                return
            values = {
                column: (row[i].strip() if i < len(row) else "") for i, column in enumerate(self._columns)
            }
            raw = "\n".join(self._lines[start_line - 1 : end_line])
            yield TableRecord(
                row_number=row_number,
                line_number=start_line,
                values=values,
                raw=raw,
                chunk_id=self._chunk_at(self._line_offsets[start_line - 1]),
            )

    def count(self) -> int:
        return sum(1 for _ in self.records())


class DocumentTextSource:
    """Page-aware text chunks of an uploaded PDF or text document (Phase 2 ingestion)."""

    def __init__(self, session: Session, document: SourceDocument) -> None:
        self.source_id = document.id
        self.source_name = document.filename
        self._chunks = [
            TextChunk(id=c.id, index=c.chunk_index, page=c.page, start_offset=c.start_offset, text=c.text)
            for c in session.scalars(
                select(SourceChunk).where(SourceChunk.document_id == document.id).order_by(SourceChunk.chunk_index)
            )
        ]

    def chunks(self) -> list[TextChunk]:
        return list(self._chunks)


def open_structured(session: Session, document: SourceDocument) -> StructuredSource:
    return CsvDocumentSource(session, document)


def open_text(session: Session, document: SourceDocument) -> TextSource:
    return DocumentTextSource(session, document)


# ---------------------------------------------------------------------------------- profiling

_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_BOOLEAN = {"true", "false", "yes", "no"}


def infer_datatype(values: list[str]) -> str:
    """Infer the narrowest XSD datatype that every non-empty value satisfies."""
    present = [v.strip() for v in values if v and v.strip()]
    if not present:
        return "string"
    if all(_INTEGER.match(v) for v in present):
        return "integer"
    if all(_DECIMAL.match(v) for v in present):
        return "decimal"
    if all(v.lower() in _BOOLEAN for v in present):
        return "boolean"

    def is_date(v: str) -> bool:
        try:
            date.fromisoformat(v)
            return len(v) == 10
        except ValueError:
            return False

    def is_datetime(v: str) -> bool:
        try:
            datetime.fromisoformat(v)
            return "T" in v or " " in v
        except ValueError:
            return False

    if all(is_date(v) for v in present):
        return "date"
    if all(is_datetime(v) for v in present):
        return "dateTime"
    return "string"
