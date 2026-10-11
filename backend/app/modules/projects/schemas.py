from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.modules.ontology.schemas import OntologyCreate

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ProjectDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
BusinessDomain = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: ProjectDescription = ""
    business_domain: BusinessDomain = ""
    initial_ontology: OntologyCreate | None = None


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    description: ProjectDescription | None = None
    business_domain: BusinessDomain | None = None


class ProjectRead(BaseModel):
    id: str
    name: str
    description: str
    business_domain: str
    ontology_count: int
    created_at: datetime
    updated_at: datetime
