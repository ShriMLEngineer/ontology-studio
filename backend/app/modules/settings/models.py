"""Registered LLM configurations and graph database connections.

Secrets are never stored: a configuration names the *environment variable* that holds the API key
or password, and the value is read only when a connection is opened or tested.
"""

from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin


class LlmConfiguration(TimestampMixin, Base):
    __tablename__ = "llm_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="openai-compatible", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_env: Mapped[str | None] = mapped_column(String(120), nullable=True)
    structured_output: Mapped[str] = mapped_column(String(20), default="json_schema", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=600.0, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_test: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class GraphConnection(TimestampMixin, Base):
    __tablename__ = "graph_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    secret_env: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_test: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
