"""Provider-independent LLM abstraction.

The application only depends on :class:`LLMProvider`. Responses are always parsed into Pydantic
models; nothing returned by a model is trusted without validation, and nothing is fabricated when
no provider is configured.
"""

from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    code = "LLM_ERROR"


class LLMNotConfiguredError(LLMError):
    code = "LLM_NOT_CONFIGURED"


class LLMTransportError(LLMError):
    """The endpoint could not be reached, timed out or returned an HTTP error."""

    code = "LLM_TRANSPORT_ERROR"


class LLMOutputError(LLMError):
    """The model did not return output matching the required schema (after repair attempts)."""

    code = "LLM_INVALID_OUTPUT"

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    raw_text: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    attempts: int = 1


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> StructuredResult[T]:
        """Return ``schema`` parsed and validated from the model's reply."""
        ...
