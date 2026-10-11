"""Document parsing behind a small interface so new formats can be added without touching callers."""

import io
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentParseError(ValueError):
    pass


@dataclass(frozen=True)
class PageSpan:
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    media_type: str
    pages: list[PageSpan] = field(default_factory=list)

    @property
    def page_count(self) -> int | None:
        return len(self.pages) or None

    def page_at(self, offset: int) -> int | None:
        for span in self.pages:
            if span.start <= offset < span.end:
                return span.page
        return self.pages[-1].page if self.pages else None


class DocumentParser(Protocol):
    extensions: tuple[str, ...]
    media_type: str

    def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


class PlainTextParser:
    extensions = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json")
    media_type = "text/plain"

    _MEDIA_TYPES = {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".json": "application/json",
    }

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        text = _normalize_newlines(text).strip()
        if not text:
            raise DocumentParseError("The document contains no text.")
        suffix = PurePath(filename).suffix.lower()
        return ParsedDocument(text=text, media_type=self._MEDIA_TYPES.get(suffix, "text/plain"))


class PdfParser:
    extensions = (".pdf",)
    media_type = "application/pdf"

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise DocumentParseError("Encrypted PDFs are not supported.")
            parts: list[str] = []
            pages: list[PageSpan] = []
            offset = 0
            for number, page in enumerate(reader.pages, start=1):
                page_text = _normalize_newlines(page.extract_text() or "").strip()
                if parts:
                    parts.append("\n\n")
                    offset += 2
                parts.append(page_text)
                pages.append(PageSpan(page=number, start=offset, end=offset + len(page_text)))
                offset += len(page_text)
        except PdfReadError as error:
            raise DocumentParseError(f"The PDF could not be read: {error}") from error
        text = "".join(parts)
        if not text.strip():
            raise DocumentParseError(
                "The PDF contains no extractable text (it may be scanned; OCR is not supported)."
            )
        return ParsedDocument(text=text, media_type=self.media_type, pages=pages)


PARSERS: tuple[DocumentParser, ...] = (PlainTextParser(), PdfParser())
SUPPORTED_EXTENSIONS = tuple(ext for parser in PARSERS for ext in parser.extensions)


def parser_for(filename: str) -> DocumentParser | None:
    suffix = PurePath(filename).suffix.lower()
    return next((p for p in PARSERS if suffix in p.extensions), None)
