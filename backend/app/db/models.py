"""Imports every ORM model so that ``Base.metadata`` is complete (used by Alembic)."""

from app.db.base import Base
from app.modules.activity.models import ActivityEvent
from app.modules.discovery.models import DiscoveryRun
from app.modules.governance.models import ChangeProposal, ProposalEvent, ProposalEvidence
from app.modules.graph.models import GraphEdgeRecord, GraphVertexRecord
from app.modules.kg.models import (
    KgBuild,
    KgBuildLog,
    KgCandidateFact,
    KgEntity,
    KgEntityMention,
    KgOntologyGap,
    KgSourceMapping,
)
from app.modules.ontology.models import (
    DatatypePropertyRecord,
    ObjectPropertyRecord,
    Ontology,
    OntologyClassRecord,
    OntologyDiagramLayout,
    OntologyExtensionAxiomRecord,
    OntologyImportRecord,
    OntologyShapeRecord,
)
from app.modules.projects.models import Project
from app.modules.registry.models import OntologyVersion
from app.modules.sources.models import SourceChunk, SourceDocument
from app.modules.validation.models import ValidationRun

__all__ = [
    "ActivityEvent",
    "Base",
    "ChangeProposal",
    "DatatypePropertyRecord",
    "DiscoveryRun",
    "GraphEdgeRecord",
    "GraphVertexRecord",
    "KgBuild",
    "KgBuildLog",
    "KgCandidateFact",
    "KgEntity",
    "KgEntityMention",
    "KgOntologyGap",
    "KgSourceMapping",
    "ObjectPropertyRecord",
    "Ontology",
    "OntologyClassRecord",
    "OntologyDiagramLayout",
    "OntologyExtensionAxiomRecord",
    "OntologyImportRecord",
    "OntologyShapeRecord",
    "OntologyVersion",
    "Project",
    "ProposalEvent",
    "ProposalEvidence",
    "SourceChunk",
    "SourceDocument",
    "ValidationRun",
]
