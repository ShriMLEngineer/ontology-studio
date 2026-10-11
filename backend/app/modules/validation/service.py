from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.activity.service import record_activity
from app.modules.ontology.service import OntologyService
from app.modules.validation.models import ValidationRun
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity, ValidationIssue, ValidationReport


class ValidationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.ontologies = OntologyService(session)

    def run(self, ontology_id: str) -> ValidationReport:
        ontology, schema = self.ontologies.get_schema(ontology_id)
        issues = validate_schema(schema)
        counts = {s: sum(1 for i in issues if i.severity == s) for s in Severity}
        run = ValidationRun(
            ontology_id=ontology.id,
            draft_revision=ontology.draft_revision,
            is_valid=counts[Severity.ERROR] == 0,
            error_count=counts[Severity.ERROR],
            warning_count=counts[Severity.WARNING],
            info_count=counts[Severity.INFO],
            issues=[i.model_dump(mode="json") for i in issues],
        )
        self.session.add(run)
        outcome = "passed" if run.is_valid else "failed"
        record_activity(
            self.session,
            project_id=ontology.project_id,
            ontology_id=ontology.id,
            event_type="ontology.validated",
            summary=(
                f"Validation {outcome} for revision {ontology.draft_revision}: "
                f"{run.error_count} errors, {run.warning_count} warnings, {run.info_count} info"
            ),
            details={"draft_revision": ontology.draft_revision, "is_valid": run.is_valid},
        )
        self.session.commit()
        return self._to_report(run, ontology.draft_revision)

    def latest(self, ontology_id: str) -> ValidationReport:
        reports = self.history(ontology_id, limit=1)
        if not reports:
            raise NotFoundError(
                "This ontology has not been validated yet.", code="VALIDATION_NOT_FOUND"
            )
        return reports[0]

    def history(self, ontology_id: str, limit: int = 10) -> list[ValidationReport]:
        ontology = self.ontologies.get_ontology(ontology_id)
        stmt = (
            select(ValidationRun)
            .where(ValidationRun.ontology_id == ontology_id)
            .order_by(ValidationRun.created_at.desc())
            .limit(limit)
        )
        return [self._to_report(run, ontology.draft_revision) for run in self.session.scalars(stmt)]

    @staticmethod
    def _to_report(run: ValidationRun, current_revision: int) -> ValidationReport:
        return ValidationReport(
            id=run.id,
            ontology_id=run.ontology_id,
            draft_revision=run.draft_revision,
            current_draft_revision=current_revision,
            is_current=run.draft_revision == current_revision,
            is_valid=run.is_valid,
            error_count=run.error_count,
            warning_count=run.warning_count,
            info_count=run.info_count,
            issues=[ValidationIssue.model_validate(i) for i in run.issues],
            created_at=run.created_at,
        )
