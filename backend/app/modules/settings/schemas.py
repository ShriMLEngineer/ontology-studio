from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
EnvName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")]


class ConnectionTest(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    tested_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------- LLM


class LlmConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    base_url: Url = Field(description="OpenAI-compatible base URL, e.g. http://localhost:11434/v1")
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    api_key_env: EnvName | None = Field(
        default=None, description="Name of the server environment variable that holds the API key (never the key)"
    )
    structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=600.0, ge=5.0, le=3600.0)
    max_output_tokens: int = Field(default=4096, ge=256, le=200_000)
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""

    @field_validator("base_url")
    @classmethod
    def _http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("the base URL must start with http:// or https://")
        return value.rstrip("/")


class LlmConfigRead(BaseModel):
    id: str
    name: str
    builtin: bool
    provider: str
    base_url: str | None
    model: str | None
    api_key_env: str | None
    api_key_present: bool | None = Field(description="Whether the named environment variable is set (value never returned)")
    structured_output: str
    temperature: float
    timeout_seconds: float
    max_output_tokens: int
    description: str
    configured: bool
    last_test: ConnectionTest | None
    used_by_projects: list[str]
    updated_by: str = ""
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------------- graph


class GraphConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    kind: str
    config: dict[str, Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = Field(default_factory=dict)
    secret_env: EnvName | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class GraphConnectionRead(BaseModel):
    id: str
    name: str
    builtin: bool
    kind: str
    kind_label: str
    model: str
    config: dict[str, Any]
    secret_env: str | None
    secret_present: bool | None
    description: str
    last_test: ConnectionTest | None
    used_by_projects: list[str]
    updated_by: str = ""
    updated_at: datetime | None = None


class ConfigFieldRead(BaseModel):
    key: str
    label: str
    required: bool
    secret: bool
    placeholder: str


class GraphKindRead(BaseModel):
    id: str
    label: str
    model: str
    builtin: bool
    registrable: bool
    available: bool
    description: str
    unavailable_reason: str
    fields: list[ConfigFieldRead]


# ---------------------------------------------------------------------------------- project defaults


class ProjectDefaults(BaseModel):
    project_id: str
    default_llm_config_id: str
    default_graph_connection_id: str
    data_namespace: str | None
    effective_llm: LlmConfigRead
    effective_graph: GraphConnectionRead


class ProjectDefaultsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_llm_config_id: str | None = None
    default_graph_connection_id: str | None = None
    data_namespace: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
