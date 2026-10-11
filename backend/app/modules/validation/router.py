from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.validation.schemas import ValidationReport
from app.modules.validation.service import ValidationService

router = APIRouter(prefix="/ontologies/{ontology_id}/validations", tags=["validation"])


def get_validation_service(session: Annotated[Session, Depends(get_session)]) -> ValidationService:
    return ValidationService(session)


Service = Annotated[ValidationService, Depends(get_validation_service)]


@router.post("", response_model=ValidationReport, status_code=status.HTTP_201_CREATED)
def run_validation(ontology_id: str, service: Service) -> ValidationReport:
    """Validate the latest saved draft and persist the report."""
    return service.run(ontology_id)


@router.get("", response_model=list[ValidationReport])
def list_validations(
    ontology_id: str, service: Service, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> list[ValidationReport]:
    """Validation history, newest first (empty when the ontology was never validated)."""
    return service.history(ontology_id, limit)


@router.get("/latest", response_model=ValidationReport)
def latest_validation(ontology_id: str, service: Service) -> ValidationReport:
    return service.latest(ontology_id)
