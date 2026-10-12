from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.settings.schemas import (
    GraphConnectionInput,
    GraphConnectionRead,
    GraphKindRead,
    LlmConfigInput,
    LlmConfigRead,
    ProjectDefaults,
    ProjectDefaultsUpdate,
)
from app.modules.settings.service import SettingsService

router = APIRouter(tags=["settings"])


def get_settings_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> SettingsService:
    state = request.app.state
    if not hasattr(state, "builtin_connection_tests"):
        state.builtin_connection_tests = {}
    return SettingsService(session, state.settings, getattr(state, "llm_provider", None), state.builtin_connection_tests)


Service = Annotated[SettingsService, Depends(get_settings_service)]
Actor = Annotated[str, Query(max_length=200)]


class LlmActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


# ---------------------------------------------------------------------------------- LLM


@router.get("/settings/llm-configurations", response_model=list[LlmConfigRead])
def list_llm(service: Service) -> list[LlmConfigRead]:
    """The environment default (read-only) followed by registered configurations."""
    return service.list_llm()


@router.post("/settings/llm-configurations", response_model=LlmConfigRead, status_code=status.HTTP_201_CREATED)
def create_llm(data: LlmConfigInput, service: Service, actor: Actor = "") -> LlmConfigRead:
    return service.create_llm(data, actor)


@router.get("/settings/llm-configurations/{config_id}", response_model=LlmConfigRead)
def get_llm(config_id: str, service: Service) -> LlmConfigRead:
    return service.get_llm(config_id)


@router.put("/settings/llm-configurations/{config_id}", response_model=LlmConfigRead)
def update_llm(config_id: str, data: LlmConfigInput, service: Service, actor: Actor = "") -> LlmConfigRead:
    return service.update_llm(config_id, data, actor)


@router.delete("/settings/llm-configurations/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm(config_id: str, service: Service, actor: Actor = "") -> Response:
    service.delete_llm(config_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/settings/llm-configurations/{config_id}/test", response_model=LlmConfigRead)
def test_llm(config_id: str, service: Service) -> LlmConfigRead:
    """Explicitly verify authenticated access to the configured provider/model."""
    return service.test_llm(config_id)


@router.post("/settings/llm-configurations/{config_id}/activation", response_model=LlmConfigRead)
def set_llm_activation(
    config_id: str, data: LlmActivation, service: Service, actor: Actor = ""
) -> LlmConfigRead:
    return service.set_llm_enabled(config_id, data.enabled, actor)


# ---------------------------------------------------------------------------------- graph databases


@router.get("/settings/graph-kinds", response_model=list[GraphKindRead])
def graph_kinds(service: Service) -> list[GraphKindRead]:
    """Supported graph database kinds; kinds without an adapter are listed with the reason."""
    return service.kinds()


@router.get("/settings/graph-connections", response_model=list[GraphConnectionRead])
def list_graph(service: Service) -> list[GraphConnectionRead]:
    return service.list_graph()


@router.post("/settings/graph-connections", response_model=GraphConnectionRead, status_code=status.HTTP_201_CREATED)
def create_graph(data: GraphConnectionInput, service: Service, actor: Actor = "") -> GraphConnectionRead:
    return service.create_graph(data, actor)


@router.get("/settings/graph-connections/{connection_id}", response_model=GraphConnectionRead)
def get_graph(connection_id: str, service: Service) -> GraphConnectionRead:
    return service.get_graph(connection_id)


@router.put("/settings/graph-connections/{connection_id}", response_model=GraphConnectionRead)
def update_graph(connection_id: str, data: GraphConnectionInput, service: Service, actor: Actor = "") -> GraphConnectionRead:
    return service.update_graph(connection_id, data, actor)


@router.delete("/settings/graph-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_graph(connection_id: str, service: Service, actor: Actor = "") -> Response:
    service.delete_graph(connection_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/settings/graph-connections/{connection_id}/test", response_model=GraphConnectionRead)
def test_graph(connection_id: str, service: Service) -> GraphConnectionRead:
    """Real connection test (read-only): local database, embedded store, or SPARQL ASK on the endpoint."""
    return service.test_graph(connection_id)


# ---------------------------------------------------------------------------------- project defaults


@router.get("/projects/{project_id}/defaults", response_model=ProjectDefaults)
def project_defaults(project_id: str, service: Service) -> ProjectDefaults:
    return service.project_defaults(project_id)


@router.put("/projects/{project_id}/defaults", response_model=ProjectDefaults)
def update_project_defaults(
    project_id: str, data: ProjectDefaultsUpdate, service: Service, actor: Actor = ""
) -> ProjectDefaults:
    return service.update_project_defaults(project_id, data, actor)
