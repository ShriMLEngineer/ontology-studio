"""Imports every ORM model so that ``Base.metadata`` is complete (used by Alembic)."""

from app.db.base import Base
from app.modules.activity.models import ActivityEvent
from app.modules.ontology.models import (
    DatatypePropertyRecord,
    ObjectPropertyRecord,
    Ontology,
    OntologyClassRecord,
    OntologyDiagramLayout,
)
from app.modules.projects.models import Project
from app.modules.validation.models import ValidationRun

__all__ = [
    "ActivityEvent",
    "Base",
    "DatatypePropertyRecord",
    "ObjectPropertyRecord",
    "Ontology",
    "OntologyClassRecord",
    "OntologyDiagramLayout",
    "Project",
    "ValidationRun",
]
