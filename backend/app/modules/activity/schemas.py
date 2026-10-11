from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    ontology_id: str | None
    event_type: str
    summary: str
    details: dict[str, Any]
    created_at: datetime
