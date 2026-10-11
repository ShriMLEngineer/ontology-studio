"""Ontology feedback: convert gaps found during KG construction into SME-reviewable proposals.

Gaps become ordinary pending change proposals (origin ``kg_build``) in the existing governance
workflow. They are aligned against the ontology's current draft to avoid duplicates, carry the
source records/quotes as evidence and never modify the draft or any published version directly.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.modules.activity.service import record_activity
from app.modules.discovery.alignment import align_findings, normalize_term
from app.modules.discovery.contract import LLMFinding
from app.modules.discovery.grounding import ChunkRef, GroundedEvidence
from app.modules.governance.models import ChangeProposal
from app.modules.governance.service import GovernanceService, persist_drafts
from app.modules.kg.models import KgBuild, KgOntologyGap
from app.modules.kg.schemas import DiscardedGap, GapProposalRequest, GapProposalResult
from app.modules.ontology.service import OntologyService
from app.modules.sources.models import SourceChunk, SourceDocument

_KIND = {
    "unknown_class": "class",
    "unknown_relationship": "object_property",
    "unknown_attribute": "datatype_property",
    "unmapped_field": "datatype_property",
}


class KgFeedbackService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _evidence(self, item: dict[str, Any]) -> GroundedEvidence | None:
        document_id = item.get("document_id") or ""
        exists = self.session.get(SourceDocument, document_id) is not None
        chunk_id = item.get("chunk_id") or ""
        if not exists or (chunk_id and self.session.get(SourceChunk, chunk_id) is None):
            chunk_id = ""
        chunk = ChunkRef(
            id=chunk_id,
            label="",
            document_id=document_id if exists else "",
            document_name=item.get("document_name", "unknown"),
            page=item.get("page"),
            start_offset=0,
            text="",
        )
        if item.get("kind") == "record":
            record = item.get("record") or {}
            context = f"Row {item.get('row_number')} of {item.get('document_name')}: " + "; ".join(
                f"{k} = {v}" for k, v in record.items() if v
            )
            quote = item.get("raw") or context
            return GroundedEvidence(
                chunk=chunk, quote=quote[:2000], context=context[:2000], start_offset=None, end_offset=None,
                verified=True, llm_quote="",
            )
        if not item.get("located") or not item.get("quote"):
            return None
        return GroundedEvidence(
            chunk=chunk,
            quote=item["quote"],
            context=item.get("context") or "",
            start_offset=item.get("start_offset"),
            end_offset=item.get("end_offset"),
            verified=True,
            llm_quote=item.get("llm_quote") or "",
        )

    def _expand(self, build: KgBuild, selected: list[KgOntologyGap]) -> list[KgOntologyGap]:
        """Include open class gaps that selected relationship/attribute gaps depend on."""
        open_classes = {
            normalize_term(g.label): g
            for g in self.session.scalars(
                select(KgOntologyGap).where(
                    KgOntologyGap.build_id == build.id,
                    KgOntologyGap.gap_type == "unknown_class",
                    KgOntologyGap.status == "open",
                )
            )
        }
        result = {g.id: g for g in selected}
        for gap in selected:
            suggestion = gap.suggestion or {}
            refs = [suggestion.get("domain_ref")] if not suggestion.get("domain_id") else []
            if gap.gap_type == "unknown_relationship" and not suggestion.get("range_id"):
                refs.append(suggestion.get("range_ref"))
            for ref in refs:
                dependency = open_classes.get(normalize_term(ref or ""))
                if dependency is not None:
                    result.setdefault(dependency.id, dependency)
        return list(result.values())

    def create_proposals(self, build_id: str, data: GapProposalRequest) -> GapProposalResult:
        build = self.session.get(KgBuild, build_id)
        if build is None:
            raise NotFoundError(f"Knowledge graph build '{build_id}' was not found.", code="KG_BUILD_NOT_FOUND")
        if build.status != "completed":
            raise BusinessRuleError("Gaps can be proposed only from a completed build.", code="KG_BUILD_NOT_COMPLETED")
        gaps = list(
            self.session.scalars(
                select(KgOntologyGap).where(KgOntologyGap.id.in_(data.gap_ids), KgOntologyGap.build_id == build.id)
            )
        )
        missing = sorted(set(data.gap_ids) - {g.id for g in gaps})
        if missing:
            raise NotFoundError("Some gaps do not belong to this build.", code="KG_GAP_NOT_FOUND", details={"gap_ids": missing})
        for gap in gaps:
            active = [
                p
                for p in self.session.scalars(select(ChangeProposal).where(ChangeProposal.id.in_(gap.proposal_ids or [])))
                if p.status != "rejected"
            ]
            if active:
                raise ConflictError(
                    f"Gap '{gap.label}' already has a proposal under review ({active[0].title}).",
                    code="KG_GAP_ALREADY_PROPOSED",
                    details={"gap_id": gap.id, "proposal_id": active[0].id},
                )
        gaps = self._expand(build, gaps)

        _, schema = OntologyService(self.session).get_schema(build.ontology_id)
        findings: list[tuple[LLMFinding, list[GroundedEvidence]]] = []
        by_key: dict[tuple[str, str], KgOntologyGap] = {}
        discarded: list[DiscardedGap] = []
        for gap in gaps:
            kind = _KIND[gap.gap_type]
            suggestion = gap.suggestion or {}
            evidence = [e for e in (self._evidence(item) for item in gap.evidence or []) if e is not None]
            if not evidence:
                discarded.append(DiscardedGap(term=gap.term, reason="No verifiable source evidence is available."))
                continue
            rationale = (
                f"Ontology gap found while building knowledge graph #{build.number} with {build.ontology_name} "
                f"{build.ontology_version}: {gap.description} Seen {gap.occurrences} time(s)."
            )
            finding = LLMFinding(
                action="add",
                element_kind=kind,  # type: ignore[arg-type]
                term=gap.term,
                label=gap.label,
                definition=str(suggestion.get("definition") or ""),
                domain=suggestion.get("domain_id") or suggestion.get("domain_ref"),
                range=(suggestion.get("range_id") or suggestion.get("range_ref")) if kind == "object_property" else None,
                datatype=suggestion.get("datatype") if kind == "datatype_property" else None,
                rationale=rationale,
                confidence=0.5,
                evidence=[],
            )
            findings.append((finding, evidence))
            by_key[(kind, normalize_term(gap.term))] = gap
        if not findings:
            raise BusinessRuleError(
                "None of the selected gaps has verifiable evidence to support a proposal.",
                code="KG_GAP_NO_EVIDENCE",
                details={"discarded": [d.model_dump() for d in discarded]},
            )

        alignment = align_findings(schema, findings)
        discarded += [DiscardedGap(term=d.term, reason=d.reason) for d in alignment.discarded]
        proposals = persist_drafts(
            self.session,
            ontology_id=build.ontology_id,
            run_id=None,
            drafts=alignment.proposals,
            origin="kg_build",
            kg_build_id=build.id,
            actor=data.requested_by,
            comment=data.comment,
        )
        included: list[str] = []
        for draft, proposal in zip(alignment.proposals, proposals, strict=True):
            original = draft.llm_output or {}
            gap = by_key.get((original.get("element_kind", ""), normalize_term(original.get("term", ""))))
            proposal.confidence = None
            proposal.llm_output = None
            proposal.alignment = {
                **proposal.alignment,
                "llm_action": None,
                "notes": [
                    f"Created from an ontology gap in knowledge graph build #{build.number} "
                    f"({build.ontology_version}) by {data.requested_by}.",
                    *proposal.alignment.get("notes", []),
                ],
            }
            if gap is not None:
                gap.status = "proposed"
                gap.proposal_ids = [*(gap.proposal_ids or []), proposal.id]
                included.append(gap.id)
        record_activity(
            self.session,
            project_id=build.project_id,
            ontology_id=build.ontology_id,
            event_type="kg.gap_proposed",
            summary=f"{len(proposals)} ontology change proposal(s) created from gaps in knowledge graph build "
            f"#{build.number} for SME review",
            details={"build_id": build.id, "proposal_ids": [p.id for p in proposals]},
        )
        self.session.commit()
        governance = GovernanceService(self.session)
        summaries = {s.id: s for s in governance.list_proposals(build.ontology_id, kg_build_id=build.id)}
        return GapProposalResult(
            proposals=[summaries[p.id] for p in proposals if p.id in summaries],
            included_gap_ids=list(dict.fromkeys(included)),
            discarded=discarded,
        )
