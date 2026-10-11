"""SME review and governance of ontology change proposals.

Proposals never change a published version. Approved proposals are applied to the editable draft
only through an explicit apply step, in dependency order, with per-proposal failure isolation.
"""

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import new_element_id, utcnow
from app.modules.activity.service import record_activity
from app.modules.discovery.alignment import ProposalDraft, make_title
from app.modules.governance.apply import (
    COLLECTIONS,
    DEFINITION_MODELS,
    EDITABLE_FIELDS,
    ApplyError,
    ChangeSpec,
    apply_change,
    assess_impact,
)
from app.modules.governance.models import ChangeProposal, ProposalEvent, ProposalEvidence
from app.modules.governance.schemas import (
    ApplyFailure,
    ApplyRequest,
    ApplyResult,
    CommentCreate,
    DecisionRequest,
    EvidenceRead,
    ProposalDetail,
    ProposalEventRead,
    ProposalImpact,
    ProposalStats,
    ProposalSummary,
    ProposalUpdate,
)
from app.modules.ontology.domain import OntologySchema
from app.modules.ontology.models import Ontology
from app.modules.ontology.schemas import DraftChangeSummary
from app.modules.ontology.service import OntologyService

AI_ACTOR = "AI discovery"
EDITABLE_STATUSES = {"pending", "needs_refinement"}
ID_PREFIX = {"class": "cls", "object_property": "op", "datatype_property": "dp"}
_TYPE_ORDER = {"add": 0, "modify": 1, "alias": 2, "conflict": 3, "reuse": 4}
_KIND_ORDER = {"class": 0, "object_property": 1, "datatype_property": 2}


def spec_of(proposal: ChangeProposal) -> ChangeSpec:
    return ChangeSpec(
        proposal_type=proposal.proposal_type,
        element_kind=proposal.element_kind,
        target_element_id=proposal.target_element_id,
        new_element=proposal.new_element,
        changes=proposal.changes or {},
    )


def persist_drafts(
    session: Session, *, ontology_id: str, run_id: str | None, drafts: list[ProposalDraft]
) -> list[ChangeProposal]:
    """Store aligned discovery drafts as pending proposals with their verified evidence."""
    created: dict[str, ChangeProposal] = {}
    for draft in drafts:
        proposal = ChangeProposal(
            ontology_id=ontology_id,
            run_id=run_id,
            proposal_type=draft.proposal_type,
            element_kind=draft.element_kind,
            status="pending",
            title=draft.title,
            term=draft.term[:200],
            rationale=draft.rationale,
            confidence=draft.confidence,
            target_element_id=draft.target_element_id,
            new_element=draft.new_element,
            changes=draft.changes,
            alignment=draft.alignment,
            depends_on=[],
            llm_output=draft.llm_output,
        )
        session.add(proposal)
        session.flush()
        created[draft.key] = proposal
        for evidence in draft.evidence:
            if not evidence.verified:
                continue
            session.add(
                ProposalEvidence(
                    proposal_id=proposal.id,
                    document_id=evidence.chunk.document_id if evidence.chunk else None,
                    chunk_id=evidence.chunk.id if evidence.chunk else None,
                    document_name=evidence.chunk.document_name if evidence.chunk else "unknown",
                    page=evidence.chunk.page if evidence.chunk else None,
                    quote=evidence.quote,
                    context=evidence.context,
                    start_offset=evidence.start_offset,
                    end_offset=evidence.end_offset,
                    verified=True,
                )
            )
        session.add(
            ProposalEvent(
                proposal_id=proposal.id,
                event_type="created",
                actor=AI_ACTOR,
                details={"llm_action": draft.alignment.get("llm_action"), "notes": draft.alignment.get("notes", [])},
            )
        )
    for draft in drafts:
        created[draft.key].depends_on = [created[k].id for k in draft.depends_on if k in created]
    return list(created.values())


class GovernanceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.ontologies = OntologyService(session)

    # ------------------------------------------------------------------------------ helpers

    def _require_ontology(self, ontology_id: str) -> Ontology:
        return self.ontologies._require(ontology_id)

    def _require(self, proposal_id: str) -> ChangeProposal:
        proposal = self.session.get(ChangeProposal, proposal_id)
        if proposal is None:
            raise NotFoundError(f"Proposal '{proposal_id}' was not found.", code="PROPOSAL_NOT_FOUND")
        return proposal

    def _draft_schema(self, ontology_id: str) -> tuple[Ontology, OntologySchema]:
        return self.ontologies.get_schema(ontology_id)

    @staticmethod
    def _labels(schema: OntologySchema) -> dict[str, str]:
        return {e.id: e.label for e in (*schema.classes, *schema.object_properties, *schema.datatype_properties)}

    def _evidence_counts(self, ids: list[str]) -> dict[str, int]:
        if not ids:
            return {}
        stmt = (
            select(ProposalEvidence.proposal_id, func.count())
            .where(ProposalEvidence.proposal_id.in_(ids))
            .group_by(ProposalEvidence.proposal_id)
        )
        return dict(self.session.execute(stmt).all())  # type: ignore[arg-type]

    def _summary(self, proposal: ChangeProposal, labels: dict[str, str], evidence_count: int) -> ProposalSummary:
        target_label = labels.get(proposal.target_element_id or "")
        if target_label is None and proposal.new_element:
            target_label = proposal.new_element.get("label")
        return ProposalSummary(
            id=proposal.id,
            ontology_id=proposal.ontology_id,
            run_id=proposal.run_id,
            proposal_type=proposal.proposal_type,  # type: ignore[arg-type]
            element_kind=proposal.element_kind,  # type: ignore[arg-type]
            status=proposal.status,  # type: ignore[arg-type]
            title=proposal.title,
            term=proposal.term,
            confidence=proposal.confidence,
            target_element_id=proposal.target_element_id,
            target_label=target_label,
            evidence_count=evidence_count,
            edited=proposal.edited,
            applied_draft_revision=proposal.applied_draft_revision,
            apply_error=proposal.apply_error,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )

    def _event(self, proposal: ChangeProposal, event_type: str, actor: str, comment: str = "", **details: Any) -> None:
        self.session.add(
            ProposalEvent(proposal_id=proposal.id, event_type=event_type, actor=actor, comment=comment, details=details)
        )

    def _dependency_chain(self, proposal: ChangeProposal) -> list[ChangeProposal]:
        """Unapplied dependencies in application order, followed by the proposal itself."""
        chain: list[ChangeProposal] = []
        seen: set[str] = set()

        def visit(current: ChangeProposal) -> None:
            if current.id in seen:
                return
            seen.add(current.id)
            for dep_id in current.depends_on or []:
                dependency = self.session.get(ChangeProposal, dep_id)
                if dependency is not None and dependency.status != "applied":
                    visit(dependency)
            chain.append(current)

        visit(proposal)
        return chain

    def _impact(self, proposal: ChangeProposal, schema: OntologySchema) -> ProposalImpact:
        chain = self._dependency_chain(proposal)
        rejected = [p for p in chain[:-1] if p.status == "rejected"]
        if rejected:
            return ProposalImpact(
                applicable=False,
                reason=f"Depends on rejected proposal '{rejected[0].title}'.",
                blocking=True,
                introduced_issues=[],
                resolved_issues=[],
            )
        impact = assess_impact(schema, [spec_of(p) for p in chain])
        return ProposalImpact(
            applicable=impact.applicable,
            reason=impact.reason,
            blocking=impact.blocking,
            introduced_issues=impact.introduced,
            resolved_issues=impact.resolved,
        )

    # ------------------------------------------------------------------------------ queries

    def list_proposals(
        self, ontology_id: str, *, status: str | None = None, proposal_type: str | None = None, run_id: str | None = None
    ) -> list[ProposalSummary]:
        _, schema = self._draft_schema(ontology_id)
        stmt = select(ChangeProposal).where(ChangeProposal.ontology_id == ontology_id)
        if status:
            stmt = stmt.where(ChangeProposal.status == status)
        if proposal_type:
            stmt = stmt.where(ChangeProposal.proposal_type == proposal_type)
        if run_id:
            stmt = stmt.where(ChangeProposal.run_id == run_id)
        proposals = list(self.session.scalars(stmt.order_by(ChangeProposal.created_at.desc(), ChangeProposal.id)))
        counts = self._evidence_counts([p.id for p in proposals])
        labels = self._labels(schema)
        return [self._summary(p, labels, counts.get(p.id, 0)) for p in proposals]

    def stats(self, ontology_id: str) -> ProposalStats:
        self._require_ontology(ontology_id)
        rows = self.session.execute(
            select(ChangeProposal.status, ChangeProposal.proposal_type).where(ChangeProposal.ontology_id == ontology_id)
        ).all()
        by_status = Counter(status for status, _ in rows)
        by_type = Counter(kind for _, kind in rows)
        return ProposalStats(
            total=len(rows),
            awaiting_review=by_status["pending"] + by_status["needs_refinement"],
            approved_not_applied=by_status["approved"],
            by_status=dict(by_status),
            by_type=dict(by_type),
        )

    def get_proposal(self, proposal_id: str) -> ProposalDetail:
        proposal = self._require(proposal_id)
        _, schema = self._draft_schema(proposal.ontology_id)
        labels = self._labels(schema)
        evidence = list(
            self.session.scalars(
                select(ProposalEvidence)
                .where(ProposalEvidence.proposal_id == proposal.id)
                .order_by(ProposalEvidence.created_at, ProposalEvidence.id)
            )
        )
        events = list(
            self.session.scalars(
                select(ProposalEvent)
                .where(ProposalEvent.proposal_id == proposal.id)
                .order_by(ProposalEvent.created_at, ProposalEvent.id)
            )
        )
        target = None
        if proposal.target_element_id:
            element = next(
                (e for e in getattr(schema, COLLECTIONS[proposal.element_kind]) if e.id == proposal.target_element_id),
                None,
            )
            target = element.model_dump(mode="json") if element else None
        summary = self._summary(proposal, labels, len(evidence))
        return ProposalDetail(
            **summary.model_dump(),
            rationale=proposal.rationale,
            new_element=proposal.new_element,
            changes=proposal.changes or {},
            alignment=proposal.alignment or {},
            depends_on=proposal.depends_on or [],
            llm_output=proposal.llm_output,
            target=target,
            evidence=[EvidenceRead.model_validate(e) for e in evidence],
            events=[ProposalEventRead.model_validate(e) for e in events],
            impact=None if proposal.status == "applied" else self._impact(proposal, schema),
        )

    # ------------------------------------------------------------------------------ commands

    def update_proposal(self, proposal_id: str, data: ProposalUpdate) -> ProposalDetail:
        proposal = self._require(proposal_id)
        if proposal.status not in EDITABLE_STATUSES:
            raise ConflictError(
                f"Only pending proposals or proposals needing refinement can be edited (status: {proposal.status}).",
                code="PROPOSAL_NOT_EDITABLE",
            )
        _, schema = self._draft_schema(proposal.ontology_id)
        kind = proposal.element_kind
        new_type = data.proposal_type or proposal.proposal_type
        requested = data.model_dump(exclude_unset=True)
        target_id = requested.get("target_element_id", proposal.target_element_id)

        target = None
        if new_type != "add":
            target = next((e for e in getattr(schema, COLLECTIONS[kind]) if e.id == target_id), None)
            if target is None:
                raise BusinessRuleError(
                    f"A {new_type} proposal needs an existing {kind.replace('_', ' ')} in the draft as its target.",
                    code="PROPOSAL_TARGET_REQUIRED",
                )

        new_element = proposal.new_element
        changes: dict[str, dict[str, Any]] = {}
        alias: str | None = None
        if new_type == "add":
            source = data.new_element if data.new_element is not None else proposal.new_element
            if not source:
                raise BusinessRuleError("An add proposal must define the element to add.", code="PROPOSAL_INVALID")
            source = {**source, "id": source.get("id") or new_element_id(ID_PREFIX[kind])}
            try:
                new_element = DEFINITION_MODELS[kind].model_validate(source).model_dump(mode="json")
            except ValueError as error:
                raise BusinessRuleError(f"Invalid element definition: {error}", code="PROPOSAL_INVALID") from error
            target_id = None
        else:
            new_element = None
            current = target.model_dump(mode="json")  # type: ignore[union-attr]
            if new_type == "alias":
                alias = (data.alias or self._existing_alias(proposal) or "").strip()
                if not alias:
                    raise BusinessRuleError("An alias proposal needs the alias text.", code="PROPOSAL_INVALID")
                if alias.lower() not in {a.lower() for a in current["aliases"]} | {current["label"].lower()}:
                    changes = {"aliases": {"before": current["aliases"], "after": [*current["aliases"], alias]}}
            elif new_type in {"modify", "conflict"}:
                after = data.after if data.after is not None else {
                    name: change.get("after") for name, change in (proposal.changes or {}).items()
                }
                unknown = set(after) - EDITABLE_FIELDS[kind]
                if unknown:
                    raise BusinessRuleError(
                        f"Field(s) {', '.join(sorted(unknown))} cannot be changed on a {kind}.", code="PROPOSAL_INVALID"
                    )
                changes = {
                    name: {"before": current[name], "after": value}
                    for name, value in after.items()
                    if value != current[name]
                }
                if new_type == "modify" and not changes:
                    raise BusinessRuleError(
                        "A modify proposal must change at least one field.", code="PROPOSAL_INVALID"
                    )

        label = new_element["label"] if new_element else target.label  # type: ignore[union-attr]
        previous_status = proposal.status
        proposal.proposal_type = new_type
        proposal.target_element_id = target_id
        proposal.new_element = new_element
        proposal.changes = changes
        proposal.title = make_title(new_type, kind, label, alias)
        if data.rationale is not None:
            proposal.rationale = data.rationale
        proposal.edited = True
        proposal.status = "pending"
        proposal.apply_error = None
        proposal.updated_at = utcnow()
        self._event(
            proposal,
            "edited",
            data.actor,
            data.comment,
            proposal_type=new_type,
            fields=sorted(k for k in requested if k not in {"actor", "comment"}),
            previous_status=previous_status,
        )
        self.session.commit()
        return self.get_proposal(proposal.id)

    def _existing_alias(self, proposal: ChangeProposal) -> str | None:
        after = (proposal.changes or {}).get("aliases", {}).get("after") or []
        before = (proposal.changes or {}).get("aliases", {}).get("before") or []
        added = [a for a in after if a not in before]
        return added[-1] if added else proposal.term

    def decide(self, proposal_id: str, data: DecisionRequest) -> ProposalDetail:
        proposal = self._require(proposal_id)
        allowed = {
            "approve": {"pending", "needs_refinement"},
            "reject": {"pending", "needs_refinement", "approved"},
            "request_refinement": {"pending", "approved"},
            "reopen": {"rejected", "approved", "needs_refinement"},
        }[data.decision]
        if proposal.status not in allowed:
            raise ConflictError(
                f"Cannot {data.decision.replace('_', ' ')} a proposal with status '{proposal.status}'.",
                code="INVALID_PROPOSAL_TRANSITION",
                details={"status": proposal.status, "decision": data.decision},
            )
        if data.decision in {"reject", "request_refinement"} and not data.comment:
            raise BusinessRuleError("Please record a comment explaining this decision.", code="COMMENT_REQUIRED")

        if data.decision == "approve":
            _, schema = self._draft_schema(proposal.ontology_id)
            impact = self._impact(proposal, schema)
            if not impact.applicable:
                raise BusinessRuleError(
                    f"This proposal cannot be applied to the current draft: {impact.reason}",
                    code="PROPOSAL_NOT_APPLICABLE",
                )
            errors = [i for i in impact.introduced_issues if i.severity == "error"]
            if errors:
                raise BusinessRuleError(
                    "Approving this proposal would introduce blocking validation errors. Edit it first.",
                    code="PROPOSAL_INTRODUCES_ERRORS",
                    details={"issues": [i.model_dump(mode="json") for i in errors]},
                )

        new_status = {
            "approve": "approved",
            "reject": "rejected",
            "request_refinement": "needs_refinement",
            "reopen": "pending",
        }[data.decision]
        event_type = {
            "approve": "approved",
            "reject": "rejected",
            "request_refinement": "refinement_requested",
            "reopen": "reopened",
        }[data.decision]
        previous = proposal.status
        proposal.status = new_status
        proposal.updated_at = utcnow()
        self._event(proposal, event_type, data.actor, data.comment, previous_status=previous)
        ontology = self._require_ontology(proposal.ontology_id)
        record_activity(
            self.session,
            project_id=ontology.project_id,
            ontology_id=ontology.id,
            event_type=f"proposal.{event_type}",
            summary=f"{data.actor} {event_type.replace('_', ' ')}: {proposal.title}",
            details={"proposal_id": proposal.id},
        )
        self.session.commit()
        return self.get_proposal(proposal.id)

    def add_comment(self, proposal_id: str, data: CommentCreate) -> ProposalEventRead:
        proposal = self._require(proposal_id)
        event = ProposalEvent(proposal_id=proposal.id, event_type="commented", actor=data.actor, comment=data.body)
        self.session.add(event)
        self.session.commit()
        return ProposalEventRead.model_validate(event)

    def apply_approved(self, ontology_id: str, data: ApplyRequest) -> ApplyResult:
        ontology, schema = self._draft_schema(ontology_id)
        stmt = select(ChangeProposal).where(ChangeProposal.ontology_id == ontology_id, ChangeProposal.status == "approved")
        approved = {p.id: p for p in self.session.scalars(stmt)}
        if data.proposal_ids is not None:
            not_approved = [pid for pid in data.proposal_ids if pid not in approved]
            if not_approved:
                raise BusinessRuleError(
                    "Only approved proposals can be applied.",
                    code="PROPOSALS_NOT_APPROVED",
                    details={"proposal_ids": not_approved},
                )
            approved = {pid: approved[pid] for pid in data.proposal_ids}
        if not approved:
            raise BusinessRuleError("There are no approved proposals to apply.", code="NOTHING_TO_APPLY")

        ordered = self._application_order(list(approved.values()))
        applied: list[ChangeProposal] = []
        failed: list[tuple[ChangeProposal, str]] = []
        applied_ids: set[str] = set()
        for proposal in ordered:
            blocked_by = [
                dep for dep in (proposal.depends_on or []) if dep not in applied_ids and self._status(dep) != "applied"
            ]
            if blocked_by:
                dependency = self.session.get(ChangeProposal, blocked_by[0])
                failed.append((proposal, f"Requires '{dependency.title if dependency else blocked_by[0]}' to be applied first."))
                continue
            try:
                schema = apply_change(schema, spec_of(proposal))
            except ApplyError as error:
                failed.append((proposal, str(error)))
                continue
            applied.append(proposal)
            applied_ids.add(proposal.id)

        changes = self.ontologies.replace_schema(
            ontology,
            schema,
            event_type="ontology.proposals_applied",
            summary=f"{data.actor} applied {len(applied)} approved proposal(s)",
            details={"proposal_ids": [p.id for p in applied]},
        ) if applied else None
        now = utcnow()
        for proposal in applied:
            proposal.status = "applied"
            proposal.applied_draft_revision = ontology.draft_revision
            proposal.applied_at = now
            proposal.apply_error = None
            proposal.updated_at = now
            self._event(proposal, "applied", data.actor, draft_revision=ontology.draft_revision)
        for proposal, reason in failed:
            proposal.apply_error = reason
            proposal.updated_at = now
            self._event(proposal, "apply_failed", data.actor, reason)
        self.session.commit()

        labels = self._labels(schema)
        counts = self._evidence_counts([p.id for p in applied])
        return ApplyResult(
            applied=[self._summary(p, labels, counts.get(p.id, 0)) for p in applied],
            failed=[ApplyFailure(proposal_id=p.id, title=p.title, reason=r) for p, r in failed],
            draft_revision=ontology.draft_revision,
            revision_incremented=bool(changes and changes.has_semantic_changes),
            changes=changes or DraftChangeSummary(),
        )

    def _status(self, proposal_id: str) -> str | None:
        proposal = self.session.get(ChangeProposal, proposal_id)
        return proposal.status if proposal else None

    @staticmethod
    def _application_order(proposals: list[ChangeProposal]) -> list[ChangeProposal]:
        by_id = {p.id: p for p in proposals}
        ordered: list[ChangeProposal] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(proposal: ChangeProposal) -> None:
            if proposal.id in done or proposal.id in visiting:
                return
            visiting.add(proposal.id)
            for dep in proposal.depends_on or []:
                if dep in by_id:
                    visit(by_id[dep])
            visiting.discard(proposal.id)
            done.add(proposal.id)
            ordered.append(proposal)

        for proposal in sorted(
            proposals,
            key=lambda p: (_TYPE_ORDER[p.proposal_type], _KIND_ORDER[p.element_kind], p.created_at, p.id),
        ):
            visit(proposal)
        return ordered
