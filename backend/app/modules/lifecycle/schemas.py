"""API contracts of the project lifecycle navigator."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

StageKey = Literal[
    "sources", "discovery", "review", "validation", "publication", "mapping", "kg_build", "deployment", "evaluation"
]
StageStatus = Literal["completed", "reused", "in_progress", "pending", "blocked", "outdated"]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class StageDefinition(BaseModel):
    key: StageKey
    label: str
    group: Literal["governance", "knowledge-graph"]
    description: str
    optional: bool = False


class StageLink(BaseModel):
    area: Literal["ontology", "knowledge-graph"]
    tab: str
    build_id: str | None = None


class ReusedOutput(BaseModel):
    from_iteration: int
    summary: str
    refs: dict[str, Any] = Field(default_factory=dict)


class StageRead(BaseModel):
    key: StageKey
    label: str
    status: StageStatus
    summary: str
    details: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    reused: ReusedOutput | None = None
    link: StageLink


class IterationSummary(BaseModel):
    id: str
    number: int
    name: str
    goal: str
    start_stage: StageKey
    status: Literal["active", "closed"]
    ontology_id: str | None
    base_iteration_number: int | None
    created_by: str
    started_at: datetime
    closed_at: datetime | None
    counts: dict[str, int]


class IterationDetail(IterationSummary):
    frozen: bool
    stages: list[StageRead]


class StartOption(BaseModel):
    stage: StageKey
    allowed: bool
    reason: str = ""
    reuses: list[str] = Field(default_factory=list)


class LifecycleRead(BaseModel):
    project_id: str
    ontology_id: str | None
    ontology_name: str | None
    stages: list[StageDefinition]
    iterations: list[IterationSummary]
    iteration: IterationDetail
    start_options: list[StartOption]


class IterationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_stage: StageKey
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    goal: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    ontology_id: str | None = None
    created_by: Actor
