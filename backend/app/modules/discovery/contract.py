"""Structured-output contract between the discovery prompt and the LLM.

This contract is deliberately separate from the canonical ontology model: LLM findings are
untrusted suggestions that are grounded and aligned before becoming change proposals.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

FindingAction = Literal["add", "reuse", "alias", "modify", "conflict"]
FindingKind = Literal["class", "object_property", "datatype_property"]
Datatype = Literal["string", "integer", "decimal", "boolean", "date", "dateTime", "anyURI"]


def _clamp_confidence(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number > 1 and number <= 100:
        number = number / 100
    return min(max(number, 0.0), 1.0)


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null", "n/a"}:
        return None
    return value


OptionalRef = Annotated[str | None, BeforeValidator(_empty_to_none)]


class LLMEvidence(BaseModel):
    chunk_id: str = Field(description="Id of the source chunk the quote comes from, e.g. C1")
    quote: str = Field(description="Exact text copied verbatim from that chunk (max 300 characters)")


class LLMFinding(BaseModel):
    action: Annotated[FindingAction, BeforeValidator(_lower)] = Field(
        description="add | reuse | alias | modify | conflict"
    )
    element_kind: Annotated[FindingKind, BeforeValidator(_lower)] = Field(
        description="class | object_property | datatype_property"
    )
    term: str = Field(description="The term exactly as it is used in the source text")
    label: str = Field(description="Proposed label, or the label of the existing element")
    definition: str = Field(default="", description="One or two sentence business definition")
    target_id: OptionalRef = Field(
        default=None, description="Id of the existing ontology element (reuse, alias, modify, conflict)"
    )
    alias: OptionalRef = Field(default=None, description="New synonym for the target element (alias)")
    parent: OptionalRef = Field(default=None, description="Parent class id or label (classes)")
    domain: OptionalRef = Field(default=None, description="Domain class id or label (properties)")
    range: OptionalRef = Field(default=None, description="Range class id or label (object properties)")
    datatype: Annotated[Datatype | None, BeforeValidator(_empty_to_none)] = Field(
        default=None, description="XSD datatype (datatype properties)"
    )
    rationale: str = Field(default="", description="Why the source supports this finding")
    confidence: Annotated[float, BeforeValidator(_clamp_confidence)] = Field(
        default=0.5, description="0.0 to 1.0"
    )
    evidence: list[LLMEvidence] = Field(default_factory=list, description="1-3 verbatim quotes")

    @field_validator("term", "label")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value[:200]

    @field_validator("evidence")
    @classmethod
    def _limit_evidence(cls, value: list[LLMEvidence]) -> list[LLMEvidence]:
        return value[:3]


class LLMDiscoveryResponse(BaseModel):
    findings: list[LLMFinding] = Field(default_factory=list)

    @field_validator("findings")
    @classmethod
    def _limit_findings(cls, value: list[LLMFinding]) -> list[LLMFinding]:
        return value[:40]
