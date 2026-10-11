"""Canonical, source-independent extraction model shared by structured mapping and LLM extraction.

Structured records and LLM output are both normalised into these types before entity resolution
and validation; nothing downstream depends on where a candidate came from except provenance.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

STRUCTURED = "structured"
LLM = "llm"


@dataclass
class SourceRef:
    kind: str  # "record" (structured row) or "text" (document chunk)
    document_id: str
    document_name: str
    mapping_id: str | None = None
    mapping_name: str | None = None
    row_number: int | None = None
    line_number: int | None = None
    record: dict[str, str] | None = None
    raw: str | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    quote: str | None = None
    llm_quote: str | None = None
    context: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    located: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @property
    def location(self) -> str:
        if self.kind == "record":
            return f"row {self.row_number} of {self.document_name}"
        page = f"page {self.page}, " if self.page else ""
        return f"{page}chunk {(self.chunk_index or 0) + 1} of {self.document_name}"


@dataclass
class Mention:
    key: str
    origin: str
    class_ref: str
    class_id: str | None
    identifier: str | None
    key_namespace: str
    label: str | None
    aliases: list[str]
    reference_only: bool
    source: SourceRef
    id_column: str | None = None

    @property
    def names(self) -> list[str]:
        return [n for n in (self.label, self.identifier, *self.aliases) if n]


@dataclass
class FactCandidate:
    key: str
    kind: str  # relationship | attribute
    origin: str
    subject: str | None  # mention key
    predicate_ref: str
    predicate_id: str | None
    object: str | None = None  # mention key (relationships)
    value: str | None = None  # literal (attributes)
    wrong_kind: str | None = None  # the reference resolved to the other property kind
    subject_ref: str | None = None  # raw reference as produced by the source (for messages)
    object_ref: str | None = None
    source: SourceRef = field(default_factory=lambda: SourceRef("record", "", ""))


@dataclass
class GapCandidate:
    gap_type: str  # unknown_class | unknown_relationship | unknown_attribute | unmapped_field
    term: str
    label: str
    origin: str
    evidence: SourceRef
    description: str = ""
    domain_ref: str | None = None
    domain_id: str | None = None
    range_ref: str | None = None
    range_id: str | None = None
    datatype: str | None = None
    column: str | None = None
    mapping_id: str | None = None
    fact_key: str | None = None
    sample_values: list[str] = field(default_factory=list)
    occurrences: int = 1
    definition: str = ""  # a definition stated by the model for an unknown concept (never an explanation)


@dataclass
class ExtractionResult:
    mentions: list[Mention] = field(default_factory=list)
    facts: list[FactCandidate] = field(default_factory=list)
    gaps: list[GapCandidate] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)

    def extend(self, other: "ExtractionResult") -> None:
        self.mentions += other.mentions
        self.facts += other.facts
        self.gaps += other.gaps
        self.discarded += other.discarded
