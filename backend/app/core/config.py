from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Runtime configuration. All values come from environment variables prefixed with OLS_."""

    model_config = SettingsConfigDict(
        env_prefix="OLS_",
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Ontology Lifecycle Studio"
    environment: str = "local"
    database_url: str = Field(
        default=f"sqlite:///{(DEFAULT_DATA_DIR / 'ontology_studio.db').as_posix()}"
    )
    database_echo: bool = False
    auto_migrate: bool = True
    seed_demo_data: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: str = "INFO"

    # Immutable published ontology artifacts (JSON / Turtle).
    artifact_dir: Path = DEFAULT_DATA_DIR / "artifacts"

    # OpenAI-compatible LLM endpoint (OpenAI, Azure OpenAI v1, Ollama, vLLM, LM Studio, ...).
    # Discovery is disabled until base URL and model are configured.
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 600.0
    llm_max_output_tokens: int = 4096
    llm_max_repair_attempts: int = 1

    # Source documents and discovery.
    source_max_upload_bytes: int = 10 * 1024 * 1024
    discovery_chunk_chars: int = 3000
    discovery_batch_chars: int = 6000
    discovery_max_chunks_per_run: int = 40


@lru_cache
def get_settings() -> Settings:
    return Settings()
