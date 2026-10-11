from functools import lru_cache
from pathlib import Path

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
