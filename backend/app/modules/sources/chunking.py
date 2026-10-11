import re
from dataclasses import dataclass

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class TextChunk:
    index: int
    start: int
    end: int
    text: str


def _boundaries(text: str) -> list[int]:
    """Preferred split offsets: paragraph ends first, then sentence ends."""
    points = {m.end() for m in _PARAGRAPH.finditer(text)}
    points |= {m.end() for m in _SENTENCE_END.finditer(text)}
    return sorted(points)


def chunk_text(text: str, max_chars: int) -> list[TextChunk]:
    """Split text into chunks of at most ``max_chars`` at paragraph/sentence boundaries.

    Offsets refer to the original text so evidence quotes can be located precisely.
    """
    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    boundaries = _boundaries(text)
    chunks: list[TextChunk] = []
    start = 0
    length = len(text)
    while start < length:
        limit = min(start + max_chars, length)
        end = limit
        if limit < length:
            candidates = [b for b in boundaries if start + max_chars // 3 <= b <= limit]
            if candidates:
                end = candidates[-1]
            else:
                space = text.rfind(" ", start + max_chars // 2, limit)
                end = space + 1 if space > start else limit
        raw = text[start:end]
        stripped_start = start + (len(raw) - len(raw.lstrip()))
        stripped = raw.strip()
        if stripped:
            chunks.append(
                TextChunk(index=len(chunks), start=stripped_start, end=stripped_start + len(stripped), text=stripped)
            )
        start = end
    return chunks


def chunk_pages(text: str, pages: list[tuple[int, int]], max_chars: int) -> list[TextChunk]:
    """Chunk each page span separately so that every chunk lies on exactly one page.

    ``pages`` holds (start, end) offsets into ``text``; chunk offsets refer to the full text.
    """
    chunks: list[TextChunk] = []
    for page_start, page_end in pages:
        for chunk in chunk_text(text[page_start:page_end], max_chars):
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    start=page_start + chunk.start,
                    end=page_start + chunk.end,
                    text=chunk.text,
                )
            )
    return chunks
