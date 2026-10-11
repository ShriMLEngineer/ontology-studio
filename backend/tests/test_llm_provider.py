import json
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.modules.llm.openai_compatible import (
    OpenAICompatibleProvider,
    extract_json_text,
    inline_schema_refs,
)
from app.modules.llm.provider import LLMOutputError, LLMTransportError


class Item(BaseModel):
    name: str
    score: float = Field(ge=0, le=1)


class Answer(BaseModel):
    items: list[Item]


def _completion(content: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _provider(handler: Any, **kwargs: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx2.MockTransport(handler),
        **kwargs,
    )


def test_request_contains_model_schema_and_auth_header() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_completion('{"items": [{"name": "a", "score": 0.5}]}'))

    result = _provider(handler, api_key="secret-key").generate_structured(
        system="sys", user="usr", schema=Answer, schema_name="answer"
    )
    assert result.value.items[0].name == "a"
    assert result.attempts == 1
    request = seen[0]
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.0
    schema = body["response_format"]["json_schema"]["schema"]
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert body["messages"][0]["role"] == "system" and "JSON Schema" in body["messages"][0]["content"]


def test_json_object_and_prompt_modes() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=_completion('{"items": []}'))

    _provider(handler, structured_output="json_object").generate_structured(
        system="s", user="u", schema=Answer, schema_name="a"
    )
    _provider(handler, structured_output="prompt").generate_structured(
        system="s", user="u", schema=Answer, schema_name="a"
    )
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in bodies[1]


def test_markdown_fences_and_prose_are_tolerated() -> None:
    assert extract_json_text('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json_text('Here you go: {"a": 1} thanks') == '{"a": 1}'


def test_invalid_output_is_repaired_once() -> None:
    replies = iter(['{"items": [{"name": "a", "score": 7}]}', '{"items": [{"name": "a", "score": 0.7}]}'])
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=_completion(next(replies)))

    result = _provider(handler).generate_structured(system="s", user="u", schema=Answer, schema_name="a")
    assert result.attempts == 2
    assert result.value.items[0].score == 0.7
    assert result.usage.prompt_tokens == 20 and result.usage.completion_tokens == 10
    repair_message = requests[1]["messages"][-1]["content"]
    assert "did not match the required JSON Schema" in repair_message and "items.0.score" in repair_message


def test_persistently_invalid_output_raises() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_completion("not json at all"))

    with pytest.raises(LLMOutputError) as error:
        _provider(handler, max_repair_attempts=1).generate_structured(
            system="s", user="u", schema=Answer, schema_name="a"
        )
    assert "after 2 attempt" in str(error.value)


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx2.Response(500, text="boom"),
        lambda request: (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=request)),
        lambda request: (_ for _ in ()).throw(httpx2.ConnectError("refused", request=request)),
        lambda request: httpx2.Response(200, json={"unexpected": True}),
    ],
)
def test_transport_failures_raise_transport_error(handler: Any) -> None:
    with pytest.raises(LLMTransportError):
        _provider(handler).generate_structured(system="s", user="u", schema=Answer, schema_name="a")


def test_check_connection_reports_model_availability() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/models"
        return httpx2.Response(200, json={"data": [{"id": "test-model"}, {"id": "other"}]})

    reachable, detail, available = _provider(handler).check_connection()
    assert reachable and available and "reachable" in detail


def test_inline_schema_refs_resolves_nested_definitions() -> None:
    schema = inline_schema_refs(Answer.model_json_schema())
    assert schema["properties"]["items"]["items"]["properties"]["name"]["type"] == "string"


def test_status_endpoint_reports_unconfigured_llm(client: TestClient) -> None:
    status = client.get("/api/llm/status").json()
    assert status["configured"] is False
    assert "OLS_LLM_BASE_URL" in status["detail"]


def test_status_endpoint_never_exposes_api_key(db_path: Any) -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    settings = make_settings(
        db_path, llm_base_url="http://llm.internal:11434/v1", llm_model="m", llm_api_key="super-secret"
    )
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/api/llm/status")
    assert response.json()["configured"] is True
    assert response.json()["endpoint_host"] == "llm.internal:11434"
    assert "super-secret" not in response.text
