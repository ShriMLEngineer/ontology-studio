"""Deterministic grounding of LLM evidence in the actual source text.

An evidence quote is *verified* only if it can be located in a source chunk. Verified evidence
stores the exact source span (not the model's paraphrase), so reviewers always see real text.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

_TRANSLATE = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u00a0": " ", "\u2026": "...",
    }
)
_CONTEXT_CHARS = 160
_MIN_QUOTE_CHARS = 3
_FUZZY_MIN_CHARS = 20
_FUZZY_THRESHOLD = 0.9


@dataclass(frozen=True)
class ChunkRef:
    id: str
    label: str
    document_id: str
    document_name: str
    page: int | None
    start_offset: int
    text: str


@dataclass(frozen=True)
class GroundedEvidence:
    chunk: ChunkRef | None
    quote: str
    context: str
    start_offset: int | None
    end_offset: int | None
    verified: bool
    llm_quote: str


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    mapping: list[int] = []
    previous_space = True
    for index, raw in enumerate(text.translate(_TRANSLATE)):
        if raw.isspace():
            if previous_space:
                continue
            chars.append(" ")
            previous_space = True
        else:
            chars.append(raw.lower())
            previous_space = False
        mapping.append(index)
    while chars and chars[-1] == " ":
        chars.pop()
        mapping.pop()
    return "".join(chars), mapping


def _quote_core(quote: str) -> str:
    quote = quote.translate(_TRANSLATE).strip().strip('"').strip("'").strip()
    if "..." in quote:
        quote = max(quote.split("..."), key=len).strip()
    return quote


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Return the (start, end) span of ``quote`` within ``text`` or ``None``."""
    needle, _ = _normalize_with_map(_quote_core(quote))
    if len(needle) < _MIN_QUOTE_CHARS:
        return None
    haystack, mapping = _normalize_with_map(text)
    position = haystack.find(needle)
    if position >= 0:
        return mapping[position], mapping[position + len(needle) - 1] + 1
    if len(needle) >= _FUZZY_MIN_CHARS:
        block = SequenceMatcher(None, haystack, needle, autojunk=False).find_longest_match(
            0, len(haystack), 0, len(needle)
        )
        if block.size >= _FUZZY_THRESHOLD * len(needle):
            return mapping[block.a], mapping[block.a + block.size - 1] + 1
    return None


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - _CONTEXT_CHARS)
    right = min(len(text), end + _CONTEXT_CHARS)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right].strip()}{suffix}"


def _normalize_label(label: str) -> str:
    return label.strip().strip("[]").replace("chunk", "").replace("Chunk", "").strip().upper()


def ground_quote(
    quote: str, chunk_label: str, batch: dict[str, ChunkRef], all_chunks: list[ChunkRef]
) -> GroundedEvidence:
    preferred = batch.get(_normalize_label(chunk_label))
    candidates = ([preferred] if preferred else []) + [c for c in batch.values() if c is not preferred]
    candidates += [c for c in all_chunks if c.id not in {x.id for x in candidates}]
    for chunk in candidates:
        span = locate_quote(quote, chunk.text)
        if span:
            start, end = span
            return GroundedEvidence(
                chunk=chunk,
                quote=chunk.text[start:end],
                context=_context(chunk.text, start, end),
                start_offset=chunk.start_offset + start,
                end_offset=chunk.start_offset + end,
                verified=True,
                llm_quote=quote,
            )
    return GroundedEvidence(
        chunk=preferred,
        quote=quote.strip()[:500],
        context="",
        start_offset=None,
        end_offset=None,
        verified=False,
        llm_quote=quote,
    )
