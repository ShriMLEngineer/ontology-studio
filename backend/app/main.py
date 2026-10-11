import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.db import models as _all_models  # noqa: F401  (registers every table for FK resolution)
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory, get_session
from app.modules.activity.router import router as activity_router
from app.modules.llm.service import build_llm_provider
from app.modules.llm.service import router as llm_router
from app.modules.ontology.router import router as ontology_router
from app.modules.projects.router import router as projects_router
from app.modules.seed.service import seed_demo_data
from app.modules.sources.router import router as sources_router
from app.modules.validation.router import router as validation_router

logger = logging.getLogger("ontology_studio")


class HealthRead(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    database: str


def _health_router() -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=HealthRead)
    def health(request: Request, session: Annotated[Session, Depends(get_session)]) -> HealthRead:
        settings: Settings = request.app.state.settings
        try:
            session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:  # pragma: no cover - surfaced to the UI as degraded status
            logger.exception("Database health check failed")
            database = "unavailable"
        return HealthRead(
            status="ok" if database == "ok" else "degraded",
            app=settings.app_name,
            version=__version__,
            environment=settings.environment,
            database=database,
        )

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    engine = create_db_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.auto_migrate:
            upgrade_database(settings.database_url)
        if settings.seed_demo_data:
            with session_factory() as session:
                seed_demo_data(session)
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Human-governed, AI-assisted ontology engineering and knowledge graph construction.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.llm_provider = build_llm_provider(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(_health_router())
    api.include_router(projects_router)
    api.include_router(activity_router)
    api.include_router(ontology_router)
    api.include_router(validation_router)
    api.include_router(llm_router)
    api.include_router(sources_router)
    app.include_router(api)
    return app
