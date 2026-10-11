"""AI-assisted ontology discovery: LLM analysis -> evidence grounding -> alignment -> proposals.

The LLM only suggests. Findings without verifiable evidence are discarded, alignment adjusts
actions to avoid duplicates and surface conflicts, and the result is stored as *pending*
proposals for SME review. Nothing here modifies an ontology draft or a published version.
"""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import utcnow
from app.modules.activity.service import record_activity
from app.modules.discovery.alignment import Discard, align_findings
from app.modules.discovery.contract import LLMDiscoveryResponse, LLMFinding
from app.modules.discovery.grounding import ChunkRef, GroundedEvidence, ground_quote
from app.modules.discovery.models import DiscoveryRun
from app.modules.discovery.prompts import PROMPT_VERSION, SYSTEM_PROMPT, PromptChunk, build_user_prompt
from app.modules.discovery.schemas import DiscoveryRunCreate, DiscoveryRunRead, RunDocument
from app.modules.governance.service import persist_drafts
from app.modules.llm.provider import LLMError, LLMOutputError, LLMProvider, LLMUsage
from app.modules.ontology.domain import OntologySchema
from app.modules.ontology.models import Ontology
from app.modules.ontology.repository import OntologyRepository
from app.modules.ontology.service import OntologyService
from app.modules.registry.models import OntologyVersion
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.sources.models import SourceChunk, SourceDocument

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")
SessionFactory = Callable[[], Session]


class DiscoveryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_read(self, run: DiscoveryRun) -> DiscoveryRunRead:
        names = dict(
            self.session.execute(
                select(SourceDocument.id, SourceDocument.filename).where(SourceDocument.id.in_(run.document_ids))
            ).all()
        )
        return DiscoveryRunRead(
            id=run.id,
            ontology_id=run.ontology_id,
            status=run.status,
            baseline_kind=run.baseline_kind,
            baseline_label=run.baseline_label,
            baseline_version_id=run.baseline_version_id,
            baseline_draft_revision=run.baseline_draft_revision,
            documents=[RunDocument(id=d, filename=names.get(d)) for d in run.document_ids],
            instructions=run.instructions,
            provider=run.provider,
            model=run.model,
            prompt_version=run.prompt_version,
            progress=run.progress or {},
            stats=run.stats or {},
            discarded=run.discarded or [],
            usage=run.usage or {},
            error=run.error,
            requested_by=run.requested_by,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def list_runs(self, ontology_id: str) -> list[DiscoveryRunRead]:
        OntologyService(self.session)._require(ontology_id)
        stmt = (
            select(DiscoveryRun)
            .where(DiscoveryRun.ontology_id == ontology_id)
            .order_by(DiscoveryRun.created_at.desc())
        )
        return [self._to_read(r) for r in self.session.scalars(stmt)]

    def get_run(self, run_id: str) -> DiscoveryRunRead:
        run = self.session.get(DiscoveryRun, run_id)
        if run is None:
            raise NotFoundError(f"Discovery run '{run_id}' was not found.", code="DISCOVERY_RUN_NOT_FOUND")
        return self._to_read(run)

    def create_run(self, ontology_id: str, data: DiscoveryRunCreate, provider: LLMProvider) -> DiscoveryRunRead:
        ontology = OntologyService(self.session)._require(ontology_id)
        active = self.session.scalars(
            select(DiscoveryRun.id).where(
                DiscoveryRun.ontology_id == ontology_id, DiscoveryRun.status.in_(ACTIVE_STATUSES)
            )
        ).first()
        if active:
            raise ConflictError(
                "A discovery run is already in progress for this ontology.",
                code="DISCOVERY_RUN_IN_PROGRESS",
                details={"run_id": active},
            )
        document_ids = list(dict.fromkeys(data.document_ids))
        found = set(
            self.session.scalars(
                select(SourceDocument.id).where(
                    SourceDocument.id.in_(document_ids), SourceDocument.project_id == ontology.project_id
                )
            )
        )
        missing = [d for d in document_ids if d not in found]
        if missing:
            raise BusinessRuleError(
                "Some documents do not exist in this project.",
                code="SOURCE_NOT_IN_PROJECT",
                details={"document_ids": missing},
            )

        if data.baseline_version_id:
            version = self.session.get(OntologyVersion, data.baseline_version_id)
            if version is None or version.ontology_id != ontology_id:
                raise BusinessRuleError(
                    "The baseline version does not belong to this ontology.", code="INVALID_BASELINE"
                )
            kind, label, revision = "version", f"published version {version.version}", version.draft_revision
        else:
            kind, label, revision = "draft", f"draft revision {ontology.draft_revision}", ontology.draft_revision

        run = DiscoveryRun(
            ontology_id=ontology_id,
            baseline_kind=kind,
            baseline_version_id=data.baseline_version_id,
            baseline_label=label,
            baseline_draft_revision=revision,
            document_ids=document_ids,
            instructions=data.instructions,
            status="queued",
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            progress={},
            stats={},
            discarded=[],
            usage={},
            requested_by=data.requested_by,
        )
        self.session.add(run)
        record_activity(
            self.session,
            project_id=ontology.project_id,
            ontology_id=ontology.id,
            event_type="discovery.started",
            summary=f"AI discovery started on {len(document_ids)} document(s) against {label} ({provider.model})",
            details={"run_id": run.id},
        )
        self.session.commit()
        return self._to_read(run)


def mark_interrupted_runs(session: Session) -> int:
    runs = list(session.scalars(select(DiscoveryRun).where(DiscoveryRun.status.in_(ACTIVE_STATUSES))))
    for run in runs:
        run.status = "failed"
        run.error = "Interrupted: the server stopped before the run finished."
        run.completed_at = utcnow()
    session.commit()
    return len(runs)


def _batches(chunks: list[ChunkRef], max_chars: int) -> list[list[ChunkRef]]:
    batches: list[list[ChunkRef]] = []
    current: list[ChunkRef] = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk.text) > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk.text)
    if current:
        batches.append(current)
    return batches


def _fail(session_factory: SessionFactory, run_id: str, message: str, usage: LLMUsage | None = None) -> None:
    with session_factory() as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.error = message[:2000]
        run.completed_at = utcnow()
        if usage:
            run.usage = {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens}
        ontology = session.get(Ontology, run.ontology_id)
        if ontology:
            record_activity(
                session,
                project_id=ontology.project_id,
                ontology_id=ontology.id,
                event_type="discovery.failed",
                summary=f"AI discovery failed: {message[:200]}",
                details={"run_id": run.id},
            )
        session.commit()


def execute_discovery_run(
    session_factory: SessionFactory, provider: LLMProvider, settings: Settings, run_id: str
) -> None:
    """Background job. Never raises; failures are recorded on the run."""
    try:
        _execute(session_factory, provider, settings, run_id)
    except Exception as error:  # noqa: BLE001 - surfaced to the user via the run record
        logger.exception("Discovery run %s failed", run_id)
        _fail(session_factory, run_id, f"Unexpected error: {error}")


def _load_inputs(
    session: Session, run: DiscoveryRun, settings: Settings
) -> tuple[OntologySchema, str, list[ChunkRef], int]:
    ontology = session.get(Ontology, run.ontology_id)
    assert ontology is not None
    if run.baseline_version_id:
        version = session.get(OntologyVersion, run.baseline_version_id)
        assert version is not None
        snapshot = OntologySnapshot.model_validate(version.snapshot)
        schema, name = snapshot.to_schema(), snapshot.metadata.name
    else:
        schema, name = OntologyRepository(session).load_schema(ontology), ontology.name

    documents = {d.id: d for d in session.scalars(select(SourceDocument).where(SourceDocument.id.in_(run.document_ids)))}
    refs: list[ChunkRef] = []
    for document_id in run.document_ids:
        document = documents.get(document_id)
        if document is None:
            continue
        stmt = select(SourceChunk).where(SourceChunk.document_id == document_id).order_by(SourceChunk.chunk_index)
        for chunk in session.scalars(stmt):
            refs.append(
                ChunkRef(
                    id=chunk.id,
                    label="",
                    document_id=document.id,
                    document_name=document.filename,
                    page=chunk.page,
                    start_offset=chunk.start_offset,
                    text=chunk.text,
                )
            )
    return schema, name, refs[: settings.discovery_max_chunks_per_run], len(refs)


def _execute(session_factory: SessionFactory, provider: LLMProvider, settings: Settings, run_id: str) -> None:
    with session_factory() as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None or run.status != "queued":
            return
        schema, ontology_name, chunks, total_chunks = _load_inputs(session, run, settings)
        baseline_label, instructions, ontology_id = run.baseline_label, run.instructions, run.ontology_id
        if not chunks:
            session.commit()
            _fail(session_factory, run_id, "The selected documents contain no text to analyse.")
            return
        batches = _batches(chunks, settings.discovery_batch_chars)
        run.status = "running"
        run.started_at = utcnow()
        run.progress = {
            "total_batches": len(batches),
            "completed_batches": 0,
            "chunks_total": total_chunks,
            "chunks_analyzed": len(chunks),
        }
        session.commit()

    collected: list[tuple[LLMFinding, dict[str, ChunkRef]]] = []
    batch_errors: list[dict[str, Any]] = []
    usage = LLMUsage()
    for number, batch in enumerate(batches, start=1):
        labeled = {f"C{i}": replace(chunk, label=f"C{i}") for i, chunk in enumerate(batch, start=1)}
        prompt = build_user_prompt(
            schema=schema,
            ontology_name=ontology_name,
            baseline_label=baseline_label,
            chunks=[PromptChunk(c.label, c.document_name, c.page, c.text) for c in labeled.values()],
            instructions=instructions,
        )
        try:
            result = provider.generate_structured(
                system=SYSTEM_PROMPT, user=prompt, schema=LLMDiscoveryResponse, schema_name="ontology_discovery"
            )
        except LLMOutputError as error:
            batch_errors.append({"batch": number, "error": str(error)})
        except LLMError as error:
            _fail(session_factory, run_id, str(error), usage)
            return
        else:
            usage = usage + result.usage
            collected += [(finding, labeled) for finding in result.value.findings]
        with session_factory() as session:
            run = session.get(DiscoveryRun, run_id)
            assert run is not None
            run.progress = {**run.progress, "completed_batches": number}
            run.usage = {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens}
            session.commit()

    if batch_errors and len(batch_errors) == len(batches):
        _fail(session_factory, run_id, f"The model returned invalid output for every batch: {batch_errors[0]['error']}", usage)
        return

    grounded: list[tuple[LLMFinding, list[GroundedEvidence]]] = []
    discarded: list[Discard] = []
    for finding, labeled in collected:
        evidence = [ground_quote(e.quote, e.chunk_id, labeled, chunks) for e in finding.evidence]
        verified = [e for e in evidence if e.verified]
        if not evidence:
            discarded.append(Discard(finding.term, finding.action, finding.element_kind, "No evidence quote was provided."))
        elif not verified:
            discarded.append(
                Discard(
                    finding.term,
                    finding.action,
                    finding.element_kind,
                    f"Evidence could not be located in the source text (quoted: \"{evidence[0].llm_quote[:80]}\").",
                )
            )
        else:
            grounded.append((finding, verified))
    alignment = align_findings(schema, grounded)

    with session_factory() as session:
        run = session.get(DiscoveryRun, run_id)
        ontology = session.get(Ontology, ontology_id)
        assert run is not None and ontology is not None
        proposals = persist_drafts(session, ontology_id=ontology_id, run_id=run_id, drafts=alignment.proposals)
        all_discarded = discarded + alignment.discarded
        by_type = Counter(p.proposal_type for p in proposals)
        run.stats = {
            "findings": len(collected),
            "proposals": len(proposals),
            "discarded": len(all_discarded),
            "by_type": dict(by_type),
            "batches": len(batches),
            "failed_batches": len(batch_errors),
            "batch_errors": batch_errors,
        }
        run.discarded = [d.as_dict() for d in all_discarded]
        run.usage = {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens}
        run.status = "completed"
        run.completed_at = utcnow()
        breakdown = ", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) or "none"
        record_activity(
            session,
            project_id=ontology.project_id,
            ontology_id=ontology.id,
            event_type="discovery.completed",
            summary=f"AI discovery produced {len(proposals)} proposal(s) for review ({breakdown}); "
            f"{len(all_discarded)} finding(s) discarded",
            details={"run_id": run.id},
        )
        session.commit()
