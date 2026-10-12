"""Project lifecycle navigator: iterations and per-iteration stage status.

Statuses are derived from the project's real records - sources, discovery runs, proposals and SME
decisions, validation runs, published versions, source mappings, KG builds, graph deployments and
evaluations - restricted to the iteration's time window. Nothing is self-reported.

* ``completed``   the stage produced its output in this iteration and it is current;
* ``reused``      the stage lies before the iteration's start stage and its output is taken over
                  from an earlier iteration (recorded when the iteration started);
* ``in_progress`` work started but is not finished (running run/build, proposals partly decided);
* ``pending``     the stage has not been done in this iteration (or waits for an upstream stage);
* ``blocked``     a gate failed (validation errors), the last attempt failed, or required
                  configuration is missing (no LLM for discovery);
* ``outdated``    the output exists but an upstream input changed after it was produced.

The active iteration is evaluated live. Starting a new iteration closes the active one and freezes
its stage statuses, so the history of every iteration stays exactly as it was when it ended.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.ids import utcnow
from app.modules.activity.service import record_activity
from app.modules.discovery.models import DiscoveryRun
from app.modules.governance.models import ChangeProposal, ProposalEvent
from app.modules.kg.connectors import is_structured
from app.modules.kg.models import KgBuild, KgGraphDeployment, KgOntologyGap, KgSourceMapping
from app.modules.lifecycle.models import ProjectIteration
from app.modules.lifecycle.schemas import (
    IterationCreate,
    IterationDetail,
    IterationSummary,
    LifecycleRead,
    ReusedOutput,
    StageDefinition,
    StageLink,
    StageRead,
    StartOption,
)
from app.modules.ontology.models import Ontology
from app.modules.projects.models import Project
from app.modules.registry.models import OntologyVersion
from app.modules.sources.models import SourceDocument
from app.modules.validation.models import ValidationRun

STAGES: list[StageDefinition] = [
    StageDefinition(key="sources", label="Sources", group="governance",
                    description="Upload documents for discovery and structured data for knowledge-graph builds."),
    StageDefinition(key="discovery", label="AI discovery", group="governance", optional=True,
                    description="LLM analysis of documents against the ontology, producing evidence-backed proposals."),
    StageDefinition(key="review", label="SME review", group="governance", optional=True,
                    description="Domain experts decide proposals (from discovery and KG feedback) and apply approved ones."),
    StageDefinition(key="validation", label="Validation", group="governance",
                    description="Structural validation of the current draft revision; errors block publication."),
    StageDefinition(key="publication", label="Publication", group="governance",
                    description="Publish an immutable, validated ontology version to the registry."),
    StageDefinition(key="mapping", label="Source mapping", group="knowledge-graph",
                    description="Map every structured source to the latest published version."),
    StageDefinition(key="kg_build", label="KG build", group="knowledge-graph",
                    description="Extract, validate and persist facts with the latest published version."),
    StageDefinition(key="deployment", label="Graph deployment", group="knowledge-graph",
                    description="Verified deployment of the latest build to the selected graph database."),
    StageDefinition(key="evaluation", label="Evaluation & feedback", group="knowledge-graph",
                    description="Review quality metrics and send ontology gaps to SME review."),
]
ORDER = {s.key: i for i, s in enumerate(STAGES)}
LABEL = {s.key: s.label for s in STAGES}
TABS = {
    "sources": ("knowledge-graph", "pipeline"),
    "discovery": ("ontology", "discovery"),
    "review": ("ontology", "review"),
    "validation": ("ontology", "validation"),
    "publication": ("ontology", "registry"),
    "mapping": ("knowledge-graph", "pipeline"),
    "kg_build": ("knowledge-graph", "pipeline"),
    "deployment": ("knowledge-graph", "deployments"),
    "evaluation": ("knowledge-graph", "evaluation"),
}
ACTIVE = ("queued", "running")
DECISIONS = ("approved", "rejected", "refinement_requested", "applied")


def _when(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _names(items: list[Any], limit: int = 3) -> str:
    names = [getattr(i, "filename", str(i)) for i in items[:limit]]
    return ", ".join(names) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _acceptance(evaluation: dict[str, Any] | None) -> float | None:
    for section in (evaluation or {}).get("sections", []):
        for metric in section.get("metrics", []):
            if metric.get("key") == "acceptance_rate" and isinstance(metric.get("value"), (int, float)):
                return float(metric["value"])
    return None


class _Records:
    """The records the stage rules read, loaded once per request."""

    def __init__(self, session: Session, project: Project, ontology: Ontology | None) -> None:
        self.project = project
        self.ontology = ontology
        self.documents = list(
            session.scalars(select(SourceDocument).where(SourceDocument.project_id == project.id).order_by(SourceDocument.created_at))
        )
        oid = ontology.id if ontology else ""
        self.runs = list(session.scalars(select(DiscoveryRun).where(DiscoveryRun.ontology_id == oid).order_by(DiscoveryRun.created_at.desc())))
        self.proposals = list(session.scalars(select(ChangeProposal).where(ChangeProposal.ontology_id == oid)))
        self.decisions = list(
            session.scalars(
                select(ProposalEvent)
                .join(ChangeProposal, ChangeProposal.id == ProposalEvent.proposal_id)
                .where(ChangeProposal.ontology_id == oid, ProposalEvent.event_type.in_(DECISIONS))
                .order_by(ProposalEvent.created_at.desc())
            )
        )
        self.validations = list(
            session.scalars(select(ValidationRun).where(ValidationRun.ontology_id == oid).order_by(ValidationRun.created_at.desc()))
        )
        self.versions = list(
            session.scalars(select(OntologyVersion).where(OntologyVersion.ontology_id == oid).order_by(OntologyVersion.sequence.desc()))
        )
        self.mappings = list(
            session.scalars(
                select(KgSourceMapping).where(KgSourceMapping.project_id == project.id, KgSourceMapping.ontology_id == oid)
            )
        )
        self.builds = list(
            session.scalars(
                select(KgBuild).where(KgBuild.project_id == project.id, KgBuild.ontology_id == oid).order_by(KgBuild.number.desc())
            )
        )
        self.builds_by_id = {b.id: b for b in self.builds}
        self.deployments = list(
            session.scalars(
                select(KgGraphDeployment)
                .where(KgGraphDeployment.project_id == project.id)
                .order_by(KgGraphDeployment.created_at.desc())
            )
        )
        self.gaps: dict[str, Counter[str]] = {}
        if self.builds:
            rows = session.execute(
                select(KgOntologyGap.build_id, KgOntologyGap.status, func.count())
                .where(KgOntologyGap.build_id.in_([b.id for b in self.builds]))
                .group_by(KgOntologyGap.build_id, KgOntologyGap.status)
            )
            for build_id, status, count in rows:
                self.gaps.setdefault(build_id, Counter())[status] = int(count)

    @property
    def text_documents(self) -> list[SourceDocument]:
        return [d for d in self.documents if not is_structured(d)]

    @property
    def structured_documents(self) -> list[SourceDocument]:
        return [d for d in self.documents if is_structured(d)]

    @property
    def latest_version(self) -> OntologyVersion | None:
        return self.versions[0] if self.versions else None

    @property
    def latest_completed_build(self) -> KgBuild | None:
        return next((b for b in self.builds if b.status == "completed"), None)

    @property
    def revision(self) -> int:
        return self.ontology.draft_revision if self.ontology else 0


@dataclass
class _Iteration:
    number: int
    start_stage: str
    started_at: datetime
    reused: dict[str, Any]

    def contains(self, value: datetime | None) -> bool:
        return value is not None and value >= self.started_at

    def is_reused(self, key: str) -> bool:
        return key in self.reused and ORDER[key] < ORDER[self.start_stage]


class _Evaluator:
    def __init__(self, records: _Records, iteration: _Iteration, llm_available: bool) -> None:
        self.r = records
        self.it = iteration
        self.llm_available = llm_available
        self.build: KgBuild | None = None  # build evaluated by the downstream KG stages

    def stage(
        self,
        key: str,
        status: str,
        summary: str,
        details: list[str] | None = None,
        updated_at: datetime | None = None,
        build_id: str | None = None,
        *,
        reused_output: bool = False,
    ) -> StageRead:
        area, tab = TABS[key]
        return StageRead(
            key=key,  # type: ignore[arg-type]
            label=LABEL[key],
            status=status,  # type: ignore[arg-type]
            summary=summary,
            details=details or [],
            updated_at=updated_at,
            reused=ReusedOutput(**self.it.reused[key]) if reused_output else None,
            link=StageLink(area=area, tab=tab, build_id=build_id),  # type: ignore[arg-type]
        )

    def reused(self, key: str, suffix: str = "", status: str = "reused", build_id: str | None = None) -> StageRead:
        info = self.it.reused[key]
        summary = f"Reused from iteration #{info['from_iteration']}: {info['summary']}" + (f" {suffix}" if suffix else "")
        return self.stage(key, status, summary, build_id=build_id, reused_output=True)

    def ref(self, key: str, name: str) -> Any:
        return (self.it.reused.get(key) or {}).get("refs", {}).get(name)

    # ------------------------------------------------------------------ governance stages

    def sources(self) -> StageRead:
        added = [d for d in self.r.documents if self.it.contains(d.created_at)]
        if added:
            structured = sum(1 for d in added if is_structured(d))
            return self.stage(
                "sources", "completed",
                f"{len(added)} source(s) added in this iteration ({structured} structured, {len(added) - structured} document(s)).",
                [d.filename for d in added[:8]], added[-1].created_at,
            )
        if self.it.is_reused("sources"):
            return self.reused("sources")
        earlier = len(self.r.documents)
        return self.stage(
            "sources", "pending",
            "No sources added in this iteration" + (f"; {earlier} available from earlier iterations." if earlier else "."),
        )

    def discovery(self) -> StageRead:
        runs = [x for x in self.r.runs if self.it.contains(x.created_at)]
        running = next((x for x in runs if x.status in ACTIVE), None)
        if running:
            return self.stage("discovery", "in_progress", f"Discovery run {running.status} ({running.model or 'LLM'}).",
                              updated_at=running.created_at)
        done = next((x for x in runs if x.status == "completed"), None)
        if runs and runs[0].status == "failed" and (done is None or runs[0].created_at > done.created_at):
            return self.stage("discovery", "blocked", f"The last discovery run failed: {runs[0].error or 'unknown error'}",
                              updated_at=runs[0].created_at)
        if done:
            proposals = sum(1 for p in self.r.proposals if p.run_id == done.id)
            newer = [d for d in self.r.text_documents if d.created_at > done.created_at]
            if newer:
                return self.stage("discovery", "outdated",
                                  f"{len(newer)} document(s) were uploaded after the last discovery run: {_names(newer)}.",
                                  updated_at=done.created_at)
            return self.stage(
                "discovery", "completed",
                f"Run of {_when(done.created_at)} produced {proposals} proposal(s) from "
                f"{len(done.document_ids or [])} document(s).", updated_at=done.completed_at or done.created_at,
            )
        if self.it.is_reused("discovery"):
            since = self.ref("discovery", "created_at")
            newer = [
                d for d in self.r.text_documents
                if since and d.created_at > datetime.fromisoformat(since) and self.it.contains(d.created_at)
            ]
            if newer:
                return self.reused("discovery", f"Since then {len(newer)} document(s) were added.", status="outdated")
            return self.reused("discovery")
        if not self.llm_available:
            return self.stage("discovery", "blocked", "No LLM is configured for this project (Settings → LLM models).")
        if not self.r.text_documents:
            return self.stage("discovery", "pending", "Waits for sources: upload a PDF or text document to analyse.")
        return self.stage("discovery", "pending", f"Ready: {len(self.r.text_documents)} document(s) can be analysed.")

    def review(self) -> StageRead:
        awaiting = [p for p in self.r.proposals if p.status in ("pending", "needs_refinement")]
        approved = [p for p in self.r.proposals if p.status == "approved"]
        decisions = [e for e in self.r.decisions if self.it.contains(e.created_at)]
        if awaiting or approved:
            origins = Counter("KG feedback" if p.origin == "kg_build" else "AI discovery" for p in awaiting + approved)
            summary = f"{len(awaiting)} proposal(s) awaiting review" + (
                f", {len(approved)} approved and not yet applied to the draft." if approved else "."
            )
            return self.stage("review", "in_progress" if decisions else "pending", summary,
                              [f"{n} from {origin}" for origin, n in origins.items()],
                              decisions[0].created_at if decisions else None)
        if decisions:
            kinds = Counter(e.event_type for e in decisions)
            return self.stage("review", "completed", f"{len(decisions)} decision(s) in this iteration; nothing awaits review.",
                              [f"{n} {kind.replace('_', ' ')}" for kind, n in kinds.items()], decisions[0].created_at)
        if self.it.is_reused("review"):
            return self.reused("review")
        return self.stage("review", "pending", "No proposals to review (they come from AI discovery and KG feedback).")

    def validation(self) -> StageRead:
        revision = self.r.revision
        runs = [v for v in self.r.validations if self.it.contains(v.created_at)]
        if runs:
            latest = runs[0]
            if latest.draft_revision < revision:
                return self.stage("validation", "outdated",
                                  f"Revision {latest.draft_revision} was validated; the draft is now at revision {revision}.",
                                  updated_at=latest.created_at)
            if not latest.is_valid:
                return self.stage("validation", "blocked",
                                  f"Revision {revision}: {latest.error_count} error(s) must be fixed before publication.",
                                  updated_at=latest.created_at)
            return self.stage("validation", "completed",
                              f"Revision {revision} is structurally valid ({latest.warning_count} warning(s)).",
                              updated_at=latest.created_at)
        if self.it.is_reused("validation"):
            validated = self.ref("validation", "draft_revision")
            if validated is not None and revision > validated:
                return self.reused("validation", f"The draft has changed since (revision {revision}).", status="outdated")
            return self.reused("validation")
        return self.stage("validation", "pending", f"Draft revision {revision} has not been validated in this iteration.")

    def publication(self) -> StageRead:
        revision = self.r.revision
        published = [v for v in self.r.versions if self.it.contains(v.published_at)]
        if published:
            version = published[0]
            if revision > version.draft_revision:
                return self.stage(
                    "publication", "outdated",
                    f"v{version.version} was published from revision {version.draft_revision}; the draft has changed "
                    f"since (revision {revision}).", updated_at=version.published_at,
                )
            return self.stage("publication", "completed", f"v{version.version} published by {version.published_by}.",
                              [f"v{v.version}" for v in published], version.published_at)
        if self.it.is_reused("publication"):
            source = self.ref("publication", "draft_revision")
            if source is not None and revision > source:
                return self.reused("publication", f"The draft has changed since (revision {revision}).", status="outdated")
            return self.reused("publication")
        current = next((v for v in self.r.validations if v.draft_revision == revision), None)
        if current is not None and not current.is_valid:
            return self.stage("publication", "blocked", f"Validation errors in revision {revision} block publication.")
        latest = self.r.latest_version
        return self.stage("publication", "pending",
                          f"Revision {revision} is not published" + (f" (latest: v{latest.version})." if latest else "."))

    # ------------------------------------------------------------------ knowledge-graph stages

    def mapping(self) -> StageRead:
        latest = self.r.latest_version
        if latest is None:
            return self.stage("mapping", "pending", "Waits for publication: mappings target a published version.")
        structured = self.r.structured_documents
        mapped = {m.document_id for m in self.r.mappings}
        unmapped = [d for d in structured if d.id not in mapped]
        stale = [m for m in self.r.mappings if m.ontology_version_id != latest.id and not self._used_with(m, latest)]
        changed = [m for m in self.r.mappings if self.it.contains(m.updated_at)]
        if changed:
            last = max(m.updated_at for m in changed)
            if unmapped:
                return self.stage("mapping", "in_progress", f"{len(unmapped)} structured source(s) without a mapping: {_names(unmapped)}.",
                                  updated_at=last)
            if stale:
                return self.stage("mapping", "outdated",
                                  f"{len(stale)} mapping(s) were validated against an older version than v{latest.version}.",
                                  [m.name for m in stale], last)
            return self.stage("mapping", "completed",
                              f"{len(self.r.mappings)} mapping(s) cover all {len(structured)} structured source(s) for v{latest.version}.",
                              [m.name for m in self.r.mappings], last)
        if self.it.is_reused("mapping"):
            if stale:
                return self.reused("mapping", f"{len(stale)} mapping(s) target an older version than v{latest.version}.",
                                   status="outdated")
            if unmapped:
                return self.stage("mapping", "pending", f"{len(unmapped)} new structured source(s) need a mapping: {_names(unmapped)}.")
            return self.reused("mapping")
        if not structured:
            return self.stage("mapping", "pending", "No structured sources to map; documents are extracted by the LLM.")
        return self.stage("mapping", "pending", f"{len(unmapped) or len(structured)} structured source(s) to map against v{latest.version}.")

    def _used_with(self, mapping: KgSourceMapping, version: OntologyVersion) -> bool:
        """A completed build of ``version`` re-checked the mapping against it at start (after its last change)."""
        return any(
            b.status == "completed"
            and b.ontology_version_id == version.id
            and mapping.id in (b.mapping_ids or [])
            and (b.started_at or b.created_at) >= mapping.updated_at
            for b in self.r.builds
        )

    def _staleness(self, build: KgBuild) -> list[str]:
        reasons: list[str] = []
        latest = self.r.latest_version
        if latest is not None and build.ontology_version_id != latest.id:
            reasons.append(f"built with v{build.ontology_version}; v{latest.version} is published")
        since = build.started_at or build.created_at
        added = [d for d in self.r.documents if d.created_at > since and d.id not in (build.source_document_ids or [])]
        if added:
            reasons.append(f"{len(added)} source(s) uploaded after build #{build.number}")
        changed = [m for m in self.r.mappings if m.id in (build.mapping_ids or []) and m.updated_at > since]
        if changed:
            reasons.append(f"{len(changed)} mapping(s) changed after build #{build.number}")
        return reasons

    def kg_build(self) -> StageRead:
        builds = [b for b in self.r.builds if self.it.contains(b.created_at)]
        running = next((b for b in builds if b.status in ACTIVE), None)
        done = next((b for b in builds if b.status == "completed"), None)
        attempt = next((b for b in builds if b.status in ("completed", "failed")), None)
        self.build = done
        if running:
            return self.stage("kg_build", "in_progress",
                              f"Build #{running.number} {running.status}" + (f": {running.current_stage}." if running.current_stage else "."),
                              updated_at=running.started_at or running.created_at, build_id=running.id)
        if attempt is not None and attempt.status == "failed":
            return self.stage("kg_build", "blocked", f"Build #{attempt.number} failed: {attempt.error or 'unknown error'}",
                              updated_at=attempt.completed_at, build_id=attempt.id)
        if done:
            facts = (done.stats or {}).get("facts", {}).get("by_status", {})
            graph = (done.stats or {}).get("graph", {})
            summary = (
                f"Build #{done.number} with v{done.ontology_version}: {facts.get('accepted', 0)} accepted, "
                f"{facts.get('rejected', 0)} rejected, {facts.get('quarantined', 0)} quarantined facts; "
                f"{graph.get('nodes', 0)} nodes, {graph.get('edges', 0)} edges."
            )
            reasons = self._staleness(done)
            if reasons:
                return self.stage("kg_build", "outdated", f"Build #{done.number} is outdated: " + "; ".join(reasons) + ".",
                                  [summary], done.completed_at, done.id)
            return self.stage("kg_build", "completed", summary, updated_at=done.completed_at, build_id=done.id)
        if self.it.is_reused("kg_build"):
            build = self.r.builds_by_id.get(self.ref("kg_build", "build_id") or "")
            self.build = build
            if build is not None:
                reasons = self._staleness(build)
                if reasons:
                    return self.reused("kg_build", "Now outdated: " + "; ".join(reasons) + ".", status="outdated", build_id=build.id)
                return self.reused("kg_build", build_id=build.id)
        if self.r.latest_version is None:
            return self.stage("kg_build", "pending", "Waits for publication: builds use published versions only.")
        configured = next((b for b in builds if b.status == "configured"), None)
        if configured:
            return self.stage("kg_build", "pending", f"Build #{configured.number} is configured but not started.",
                              build_id=configured.id)
        return self.stage("kg_build", "pending", f"Ready to build with v{self.r.latest_version.version}.")

    def deployment(self, upstream: StageRead) -> StageRead:
        build = self.build
        if build is None:
            if self.it.is_reused("deployment"):
                return self.reused("deployment")
            return self.stage("deployment", "pending", "Waits for a completed KG build.")
        target = ((build.config_snapshot or {}).get("graph_target") or {})
        target_id, target_name = target.get("id", "local-sql"), target.get("name", "Local SQL property graph")
        rows = [d for d in self.r.deployments if d.build_id == build.id]
        if self.it.contains(build.created_at):
            # A build of this iteration must reach the graph target it was configured with.
            relevant = [d for d in rows if d.target_id == target_id]
        else:
            # A reused build counts only through deployments made in this iteration, to any target.
            relevant = [d for d in rows if self.it.contains(d.created_at)]
            if not relevant:
                if self.it.is_reused("deployment"):
                    return self.reused("deployment", build_id=build.id)
                return self.stage("deployment", "pending", f"Deploy build #{build.number} to a graph database.", build_id=build.id)
        verified = next((d for d in relevant if d.status == "completed"), None)
        others = [f"Also verified in {d.target_name}" for d in rows if d.status == "completed" and (verified is None or d.target_id != verified.target_id)]
        if verified is not None:
            if upstream.status == "outdated":
                return self.stage("deployment", "outdated", f"The deployed build #{build.number} is outdated.",
                                  others, verified.completed_at, build.id)
            content = verified.stats or {}
            amount = (
                f"{content['triples']} triples" if content.get("triples")
                else f"{content.get('vertices', 0)} nodes, {content.get('edges', 0)} edges"
            )
            details = others + ([f"Last attempt failed: {relevant[0].error}"] if relevant[0].status == "failed" else [])
            return self.stage("deployment", "completed", f"Build #{build.number} verified in {verified.target_name} ({amount}).",
                              details, verified.completed_at, build.id)
        if relevant and relevant[0].status == "failed":
            return self.stage("deployment", "blocked",
                              f"Deployment of build #{build.number} to {relevant[0].target_name} failed: {relevant[0].error}",
                              others, relevant[0].completed_at, build.id)
        return self.stage("deployment", "pending", f"Deploy build #{build.number} to {target_name}.", others, build_id=build.id)

    def evaluation(self, upstream: StageRead) -> StageRead:
        build = self.build
        if build is None:
            if self.it.is_reused("evaluation"):
                return self.reused("evaluation")
            return self.stage("evaluation", "pending", "Waits for a completed KG build.")
        if not build.evaluation:
            return self.stage("evaluation", "pending", f"Build #{build.number} has no evaluation.", build_id=build.id)
        gaps = self.r.gaps.get(build.id, Counter())
        open_gaps, proposed = gaps.get("open", 0), gaps.get("proposed", 0)
        feedback = [p for p in self.r.proposals if p.kg_build_id == build.id and self.it.contains(p.created_at)]
        rate = _acceptance(build.evaluation)
        rate_text = f"acceptance rate {rate:.0%}" if rate is not None else "evaluated"
        if not self.it.contains(build.created_at) and not feedback and self.it.is_reused("evaluation"):
            return self.reused("evaluation", build_id=build.id)
        if open_gaps:
            return self.stage("evaluation", "in_progress" if feedback else "pending",
                              f"Build #{build.number}: {rate_text}; {open_gaps} ontology gap(s) not yet sent to SME review.",
                              build_id=build.id)
        if upstream.status == "outdated":
            return self.stage("evaluation", "outdated", f"Evaluation of build #{build.number}, which is outdated.", build_id=build.id)
        return self.stage("evaluation", "completed",
                          f"Build #{build.number}: {rate_text}; {proposed} gap(s) sent to SME review.",
                          updated_at=build.completed_at, build_id=build.id)

    def evaluate(self) -> list[StageRead]:
        governance = [self.sources(), self.discovery(), self.review(), self.validation(), self.publication()]
        mapping = self.mapping()
        build = self.kg_build()
        return [*governance, mapping, build, self.deployment(build), self.evaluation(build)]


# ---------------------------------------------------------------------------------- outputs and start options


def _outputs(r: _Records, from_iteration: int) -> dict[str, dict[str, Any]]:
    """The latest output of every stage, as recorded when a new iteration reuses it."""
    out: dict[str, dict[str, Any]] = {}

    def put(key: str, summary: str, **refs: Any) -> None:
        out[key] = {"from_iteration": from_iteration, "summary": summary, "refs": refs}

    if r.documents:
        structured = len(r.structured_documents)
        put("sources", f"{len(r.documents)} source(s) ({structured} structured, {len(r.documents) - structured} document(s)).",
            document_ids=[d.id for d in r.documents])
    run = next((x for x in r.runs if x.status == "completed"), None)
    if run:
        put("discovery", f"discovery run of {_when(run.created_at)}.", run_id=run.id, created_at=run.created_at.isoformat())
    decided = Counter(p.status for p in r.proposals if p.status in ("applied", "rejected"))
    if decided:
        put("review", f"{decided.get('applied', 0)} applied and {decided.get('rejected', 0)} rejected proposal(s).",
            applied=decided.get("applied", 0), rejected=decided.get("rejected", 0))
    if r.validations:
        v = r.validations[0]
        put("validation", f"validation of revision {v.draft_revision} ({'valid' if v.is_valid else f'{v.error_count} error(s)'}).",
            run_id=v.id, draft_revision=v.draft_revision, is_valid=v.is_valid)
    if r.latest_version:
        v = r.latest_version
        put("publication", f"published v{v.version}.", version_id=v.id, version=v.version, draft_revision=v.draft_revision)
    if r.mappings:
        put("mapping", f"{len(r.mappings)} source mapping(s).", mapping_ids=[m.id for m in r.mappings])
    build = r.latest_completed_build
    if build:
        put("kg_build", f"build #{build.number} with v{build.ontology_version}.", build_id=build.id, number=build.number)
        verified = [d for d in r.deployments if d.build_id == build.id and d.status == "completed"]
        if verified:
            put("deployment", f"build #{build.number} verified in {', '.join(sorted({d.target_name for d in verified}))}.",
                deployment_ids=[d.id for d in verified])
        if build.evaluation:
            put("evaluation", f"evaluation of build #{build.number}.", build_id=build.id)
    return out


def _start_requirements(r: _Records) -> dict[str, str]:
    """Stage -> reason it cannot start a new iteration (missing prerequisite output)."""
    missing: dict[str, str] = {}
    if not r.text_documents:
        missing["discovery"] = "No document to analyse."
    if not any(p.status in ("pending", "needs_refinement", "approved") for p in r.proposals):
        missing["review"] = "No proposals await review."
    if r.latest_version is None:
        missing["mapping"] = missing["kg_build"] = "No published ontology version to build with."
    elif not r.structured_documents:
        missing["mapping"] = "No structured source to map."
    if r.latest_completed_build is None:
        missing["deployment"] = missing["evaluation"] = "No completed KG build to reuse."
    return missing


class LifecycleService:
    def __init__(self, session: Session, llm_available: Callable[[str], bool] | None = None) -> None:
        self.session = session
        self.llm_available = llm_available or (lambda _project_id: False)

    # ------------------------------------------------------------------ iterations

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")
        return project

    def _iterations(self, project_id: str) -> list[ProjectIteration]:
        return list(
            self.session.scalars(
                select(ProjectIteration).where(ProjectIteration.project_id == project_id).order_by(ProjectIteration.number)
            )
        )

    def ensure_first_iteration(self, project: Project) -> ProjectIteration:
        """Iteration #1 starts with the project; created with the project (and by migration 0008)."""
        existing = self.session.scalar(select(ProjectIteration).where(ProjectIteration.project_id == project.id).limit(1))
        if existing is not None:
            return existing
        iteration = ProjectIteration(
            project_id=project.id, number=1, name="Iteration 1", goal="", start_stage="sources", reused={},
            status="active", created_by="", started_at=project.created_at,
        )
        self.session.add(iteration)
        self.session.flush()
        return iteration

    def _ontology(self, project: Project, ontology_id: str | None) -> Ontology | None:
        if ontology_id:
            ontology = self.session.get(Ontology, ontology_id)
            if ontology is not None and ontology.project_id == project.id:
                return ontology
        return self.session.scalar(
            select(Ontology).where(Ontology.project_id == project.id).order_by(Ontology.created_at).limit(1)
        )

    def _evaluate(self, records: _Records, iteration: ProjectIteration) -> list[StageRead]:
        window = _Iteration(iteration.number, iteration.start_stage, iteration.started_at, dict(iteration.reused or {}))
        return _Evaluator(records, window, self.llm_available(records.project.id)).evaluate()

    def _summary(self, iteration: ProjectIteration, stages: list[StageRead], numbers: dict[str, int]) -> dict[str, Any]:
        return {
            "id": iteration.id,
            "number": iteration.number,
            "name": iteration.name,
            "goal": iteration.goal,
            "start_stage": iteration.start_stage,
            "status": iteration.status,
            "ontology_id": iteration.ontology_id,
            "base_iteration_number": numbers.get(iteration.base_iteration_id or ""),
            "created_by": iteration.created_by,
            "started_at": iteration.started_at,
            "closed_at": iteration.closed_at,
            "counts": dict(Counter(s.status for s in stages)),
        }

    def lifecycle(self, project_id: str, iteration_id: str | None = None) -> LifecycleRead:
        project = self._project(project_id)
        self.ensure_first_iteration(project)
        self.session.commit()
        iterations = self._iterations(project.id)
        active = next((i for i in iterations if i.status == "active"), iterations[-1])
        selected = next((i for i in iterations if i.id == iteration_id), None) if iteration_id else active
        if selected is None:
            raise NotFoundError(f"Iteration '{iteration_id}' was not found in this project.", code="ITERATION_NOT_FOUND")
        numbers = {i.id: i.number for i in iterations}

        active_ontology = self._ontology(project, active.ontology_id)
        active_records = _Records(self.session, project, active_ontology)
        active_stages = self._evaluate(active_records, active)
        stages_of: dict[str, list[StageRead]] = {active.id: active_stages}
        for iteration in iterations:
            if iteration.id != active.id:
                stages_of[iteration.id] = [StageRead.model_validate(s) for s in iteration.closing_snapshot or []]

        ontology = self._ontology(project, selected.ontology_id)
        outputs = _outputs(active_records, active.number)
        missing = _start_requirements(active_records)
        options = [
            StartOption(
                stage=s.key,
                allowed=s.key not in missing,
                reason=missing.get(s.key, ""),
                reuses=[f"{LABEL[k]}: {outputs[k]['summary']}" for k in outputs if ORDER[k] < ORDER[s.key]],
            )
            for s in STAGES
        ]
        return LifecycleRead(
            project_id=project.id,
            ontology_id=ontology.id if ontology else None,
            ontology_name=ontology.name if ontology else None,
            stages=STAGES,
            iterations=[IterationSummary(**self._summary(i, stages_of[i.id], numbers)) for i in iterations],
            iteration=IterationDetail(
                **self._summary(selected, stages_of[selected.id], numbers),
                frozen=selected.id != active.id,
                stages=stages_of[selected.id],
            ),
            start_options=options,
        )

    def start_iteration(self, project_id: str, data: IterationCreate) -> LifecycleRead:
        project = self._project(project_id)
        self.ensure_first_iteration(project)
        iterations = self._iterations(project.id)
        active = next((i for i in iterations if i.status == "active"), iterations[-1])
        ontology = self._ontology(project, data.ontology_id or active.ontology_id)
        if data.ontology_id and (ontology is None or ontology.id != data.ontology_id):
            raise NotFoundError(f"Ontology '{data.ontology_id}' is not part of this project.", code="ONTOLOGY_NOT_FOUND")
        records = _Records(self.session, project, ontology)
        missing = _start_requirements(records)
        if data.start_stage in missing:
            raise BusinessRuleError(
                f"Cannot start at {LABEL[data.start_stage]}: {missing[data.start_stage]}", code="ITERATION_START_UNAVAILABLE"
            )
        # Freeze the active iteration exactly as it ends.
        snapshot = self._evaluate(_Records(self.session, project, self._ontology(project, active.ontology_id)), active)
        now = utcnow()
        active.status = "closed"
        active.closed_at = now
        active.closing_snapshot = [s.model_dump(mode="json") for s in snapshot]
        outputs = _outputs(records, active.number)
        number = max(i.number for i in iterations) + 1
        iteration = ProjectIteration(
            project_id=project.id,
            number=number,
            name=data.name or f"Iteration {number}",
            goal=data.goal,
            ontology_id=ontology.id if ontology else None,
            start_stage=data.start_stage,
            base_iteration_id=active.id,
            reused={k: v for k, v in outputs.items() if ORDER[k] < ORDER[data.start_stage]},
            status="active",
            created_by=data.created_by,
            started_at=now,
        )
        self.session.add(iteration)
        self.session.flush()
        record_activity(
            self.session,
            project_id=project.id,
            ontology_id=ontology.id if ontology else None,
            event_type="iteration.started",
            summary=f"{data.created_by} started iteration #{number} at {LABEL[data.start_stage]}"
            + (f", reusing {len(iteration.reused)} stage output(s) of iteration #{active.number}" if iteration.reused else ""),
            details={"iteration_id": iteration.id, "start_stage": data.start_stage, "reused": sorted(iteration.reused)},
        )
        self.session.commit()
        return self.lifecycle(project.id, iteration.id)
