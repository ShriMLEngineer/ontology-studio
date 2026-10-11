"""LLM provider for any OpenAI-compatible Chat Completions endpoint.

Works with OpenAI, Azure OpenAI (v1 API), Ollama, vLLM, LM Studio and similar servers. Structured
output is requested via ``response_format`` (JSON Schema or JSON mode, configurable) and always
re-validated with Pydantic. Invalid replies get a bounded number of repair attempts.
"""

import copy
import json
import logging
import re
from typing import Any, Literal

import httpx2
from pydantic import ValidationError

from app.modules.llm.provider import (
    LLMOutputError,
    LLMTransportError,
    LLMUsage,
    StructuredResult,
    T,
)

logger = logging.getLogger(__name__)

StructuredOutputMode = Literal["json_schema", "json_object", "prompt"]
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref``s so grammar-based engines (e.g. llama.cpp) can use the schema."""
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 20:
            return node
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **extra}, depth + 1)
            return {k: resolve(v, depth + 1) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        return node

    return resolve(schema)


def extract_json_text(text: str) -> str:
    """Strip Markdown fences and surrounding prose around a single JSON object."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    if cleaned.startswith("{"):
        return cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def parse_structured(text: str, schema: type[T]) -> T:
    payload = json.loads(extract_json_text(text))
    return schema.model_validate(payload)


def _summarize_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in error.errors()[:8]
        ]
        return "; ".join(parts)
    return str(error)[:500]


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        structured_output: StructuredOutputMode = "json_schema",
        temperature: float = 0.0,
        timeout_seconds: float = 600.0,
        max_output_tokens: int = 4096,
        max_repair_attempts: int = 1,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._structured_output = structured_output
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._max_repair_attempts = max_repair_attempts
        self._transport = transport

    @property
    def name(self) -> str:
        return "openai-compatible"

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    def _client(self, timeout: float) -> httpx2.Client:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
            headers["api-key"] = self._api_key  # Azure OpenAI accepts this header
        return httpx2.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx2.Timeout(timeout, connect=10.0),
            transport=self._transport,
        )

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> StructuredResult[T]:
        json_schema = inline_schema_refs(schema.model_json_schema())
        system_prompt = (
            f"{system}\n\nRespond with one JSON object only (no prose, no Markdown) that conforms "
            f"to this JSON Schema:\n{json.dumps(json_schema, separators=(',', ':'))}"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ]
        usage = LLMUsage()
        last_text = ""
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(1 + self._max_repair_attempts):
            attempts = attempt + 1
            last_text, call_usage = self._complete(messages, json_schema, schema_name)
            usage = usage + call_usage
            try:
                value = parse_structured(last_text, schema)
                return StructuredResult(value=value, raw_text=last_text, usage=usage, attempts=attempts)
            except (ValueError, ValidationError) as error:
                last_error = error
                logger.warning("LLM output failed validation (attempt %s): %s", attempts, _summarize_error(error))
                messages = [
                    *messages,
                    {"role": "assistant", "content": last_text[:8000]},
                    {
                        "role": "user",
                        "content": "Your reply did not match the required JSON Schema: "
                        f"{_summarize_error(error)}. Reply again with only the corrected JSON object.",
                    },
                ]
        raise LLMOutputError(
            f"The model returned output that does not match the required schema after {attempts} "
            f"attempt(s): {_summarize_error(last_error) if last_error else 'unknown error'}",
            raw_text=last_text,
        )

    def _complete(
        self, messages: list[dict[str, str]], json_schema: dict[str, Any], schema_name: str
    ) -> tuple[str, LLMUsage]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        if self._structured_output == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": False},
            }
        elif self._structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}

        try:
            with self._client(self._timeout) as client:
                response = client.post("/chat/completions", json=body)
        except httpx2.TimeoutException as error:
            raise LLMTransportError(
                f"The LLM endpoint did not respond within {self._timeout:.0f} seconds."
            ) from error
        except httpx2.HTTPError as error:
            raise LLMTransportError(f"Could not reach the LLM endpoint: {error}") from error

        if response.status_code >= 400:
            raise LLMTransportError(
                f"The LLM endpoint returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMTransportError("The LLM endpoint returned an unexpected response shape.") from error
        raw_usage = data.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
        )
        return content, usage

    def check_connection(self, timeout: float = 5.0) -> tuple[bool, str, bool | None]:
        """Return (reachable, detail, model_available) using the OpenAI-compatible /models API."""
        try:
            with self._client(timeout) as client:
                response = client.get("/models")
        except httpx2.HTTPError as error:
            return False, f"Endpoint unreachable: {error.__class__.__name__}", None
        if response.status_code >= 400:
            return False, f"Endpoint returned HTTP {response.status_code}", None
        try:
            ids = {str(m.get("id")) for m in response.json().get("data", [])}
        except (ValueError, AttributeError):
            return True, "Endpoint reachable (model list unavailable)", None
        available = self._model in ids if ids else None
        detail = "Endpoint reachable" + ("" if available is not False else f"; model '{self._model}' not listed")
        return True, detail, available
