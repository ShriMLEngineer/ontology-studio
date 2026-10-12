"""Read side of knowledge-graph engineering: candidate facts, entities, graph exploration with
provenance, evaluation, ontology gaps and build comparison. All graph data comes from the
configured :class:`GraphStore`."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.governance.models import ChangeProposal
from app.modules.graph.store import GraphEdge, GraphStore, GraphVertex
from app.modules.kg.models import KgBuild, KgCandidateFact, KgEntity, KgEntityMention, KgOntologyGap
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.schemas import (
    BuildComparison,
    ElementDiff,
    EntityDetail,
    EntitySummary,
    EvaluationRead,
    FacetCount,
    FactDetail,
    FactPage,
    FactSummary,
    GapProposalRef,
    GapRead,
    GraphEdgeRead,
    GraphElementDetail,
    GraphNodeRead,
    GraphPropertyRead,
    GraphRead,
    MentionRead,
    MetricComparison,
    SourceExcerpt,
)
from app.modules.kg.service import KgService, view_of
from app.modules.registry.models import OntologyVersion
from app.modules.sources.models import SourceChunk, SourceDocument

GraphStoreFactory = Callable[[Session], GraphStore]
_KIND_RANK = {"type": 0, "attribute": 1, "relationship": 2}


@dataclass
class GraphSource:
    """Where explorer reads come from: a deployment target instead of the canonical store."""

    store: GraphStore
    deployment_id: str
    label: str
    warnings: list[str] = field(default_factory=list)


class _BuildContext:
    def __init__(self, session: Session, build: KgBuild) -> None:
        self.session = session
        self.build = build

    @cached_property
    def view(self) -> OntologyView:
        version = self.session.get(OntologyVersion, self.build.ontology_version_id)
        assert version is not None
        return view_of(version)

    @cached_property
    def entities(self) -> dict[str, KgEntity]:
        return {e.id: e for e in self.session.scalars(select(KgEntity).where(KgEntity.build_id == self.build.id))}

    @cached_property
    def entity_by_vertex(self) -> dict[str, KgEntity]:
        return {e.vertex_id: e for e in self.entities.values()}

    @cached_property
    def property_by_local_name(self) -> dict[str, tuple[str, str]]:
        return {p.local_name: (p.id, p.label) for p in self.view.datatype_properties.values()}


def _source_label(fact: KgCandidateFact) -> str:
    sources = fact.sources or []
    if not sources:
        return "—"
    first = sources[0]
    if first.get("kind") == "record":
        location = f"{first.get('document_name')} · row {first.get('row_number')}"
    else:
        page = f" · p.{first['page']}" if first.get("page") else ""
        location = f"{first.get('document_name')}{page}"
    return location + (f" (+{len(sources) - 1})" if len(sources) > 1 else "")


class KgQueryService:
    def __init__(self, session: Session, graph_store_factory: GraphStoreFactory) -> None:
        self.session = session
        self.store = graph_store_factory(session)
        self.config = KgService(session)

    def _context(self, build_id: str) -> _BuildContext:
        return _BuildContext(self.session, self.config.require_build(build_id))

    # ------------------------------------------------------------------ facts

    def _fact_summary(self, fact: KgCandidateFact, ctx: _BuildContext) -> FactSummary:
        view = ctx.view
        return FactSummary(
            id=fact.id,
            sequence=fact.sequence,
            kind=fact.kind,  # type: ignore[arg-type]
            origin=fact.origin,
            status=fact.status,  # type: ignore[arg-type]
            subject_entity_id=fact.subject_entity_id,
            subject_label=fact.subject_label,
            subject_class_id=fact.subject_class_id,
            subject_class_label=view.class_label(fact.subject_class_id) or None,
            predicate_id=fact.predicate_id,
            predicate_ref=fact.predicate_ref,
            predicate_label=fact.predicate_label,
            object_entity_id=fact.object_entity_id,
            object_label=fact.object_label,
            object_class_id=fact.object_class_id,
            object_class_label=view.class_label(fact.object_class_id) or None,
            value=fact.value,
            datatype=fact.datatype,
            normalization_status=(fact.value_normalization or {}).get("status"),
            structural_passed=bool((fact.structural or {}).get("passed")),
            evidence_status=(fact.evidence or {}).get("status", "missing"),
            resolution_passed=bool((fact.resolution or {}).get("passed", True)),
            reasons=list(fact.reasons or []),
            document_ids=list(fact.document_ids or []),
            source_label=_source_label(fact),
            graph_element_id=fact.graph_element_id,
            shacl_status=_shacl_status(fact),
            policy_id=((fact.lanes or {}).get("policy") or {}).get("id"),
        )

    def _excerpts(self, fact: KgCandidateFact) -> list[SourceExcerpt]:
        excerpts: list[SourceExcerpt] = []
        for source in (fact.sources or [])[:5]:
            document_id = source.get("document_id", "")
            available = self.session.get(SourceDocument, document_id) is not None
            if source.get("kind") == "record":
                record = source.get("record") or {}
                excerpts.append(
                    SourceExcerpt(
                        document_id=document_id,
                        document_name=source.get("document_name", ""),
                        available=available,
                        row_number=source.get("row_number"),
                        record=record,
                        columns=list(record.keys()),
                    )
                )
                continue
            chunk = self.session.get(SourceChunk, source["chunk_id"]) if source.get("chunk_id") else None
            excerpts.append(
                SourceExcerpt(
                    document_id=document_id,
                    document_name=source.get("document_name", ""),
                    available=available,
                    page=source.get("page"),
                    chunk_index=source.get("chunk_index"),
                    text=chunk.text if chunk else source.get("context"),
                )
            )
        return excerpts

    def _fact_detail(self, fact: KgCandidateFact, ctx: _BuildContext) -> FactDetail:
        subject = ctx.entities.get(fact.subject_entity_id or "")
        obj = ctx.entities.get(fact.object_entity_id or "")
        return FactDetail(
            **self._fact_summary(fact, ctx).model_dump(),
            structural=fact.structural or {},
            evidence=fact.evidence or {},
            resolution=fact.resolution or {},
            sources=list(fact.sources or []),
            excerpts=self._excerpts(fact),
            lanes=fact.lanes,
            value_normalization=fact.value_normalization,
            subject_vertex_id=subject.vertex_id if subject else None,
            object_vertex_id=obj.vertex_id if obj else None,
            build_id=ctx.build.id,
            build_number=ctx.build.number,
            ontology_version=ctx.build.ontology_version,
            ontology_version_id=ctx.build.ontology_version_id,
        )

    def list_facts(
        self,
        build_id: str,
        *,
        status: str | None = None,
        kind: str | None = None,
        source_id: str | None = None,
        predicate_id: str | None = None,
        query: str | None = None,
        limit: int = 500,
    ) -> FactPage:
        ctx = self._context(build_id)
        facts = list(
            self.session.scalars(
                select(KgCandidateFact).where(KgCandidateFact.build_id == build_id).order_by(KgCandidateFact.sequence)
            )
        )
        if source_id:
            facts = [f for f in facts if source_id in (f.document_ids or [])]
        if predicate_id:
            facts = [f for f in facts if f.predicate_id == predicate_id]
        if query:
            needle = query.strip().lower()
            facts = [
                f
                for f in facts
                if needle in f" {f.subject_label} {f.predicate_label} {f.predicate_ref} {f.object_label} {f.value or ''}".lower()
            ]
        kind_counts = Counter(f.kind for f in facts)
        if kind:
            facts = [f for f in facts if f.kind == kind]
        status_counts = Counter(f.status for f in facts)
        if status:
            facts = [f for f in facts if f.status == status]
        return FactPage(
            items=[self._fact_summary(f, ctx) for f in facts[:limit]],
            total=len(facts),
            status_counts=dict(status_counts),
            kind_counts=dict(kind_counts),
        )

    def get_fact(self, fact_id: str) -> FactDetail:
        fact = self.session.get(KgCandidateFact, fact_id)
        if fact is None:
            raise NotFoundError(f"Fact '{fact_id}' was not found.", code="KG_FACT_NOT_FOUND")
        return self._fact_detail(fact, self._context(fact.build_id))

    # ------------------------------------------------------------------ entities

    @staticmethod
    def _entity_summary(entity: KgEntity) -> EntitySummary:
        return EntitySummary(
            id=entity.id,
            vertex_id=entity.vertex_id,
            class_id=entity.class_id,
            class_label=entity.class_label,
            label=entity.label,
            identifier=entity.identifier,
            resolution_method=entity.resolution_method,
            ambiguous=entity.ambiguous,
            has_master_record=entity.has_master_record,
            mention_count=entity.mention_count,
            status=entity.status,
        )

    def list_entities(self, build_id: str, *, query: str | None = None, method: str | None = None) -> list[EntitySummary]:
        self.config.require_build(build_id)
        stmt = select(KgEntity).where(KgEntity.build_id == build_id)
        if method:
            stmt = stmt.where(KgEntity.resolution_method == method)
        entities = list(self.session.scalars(stmt.order_by(KgEntity.class_label, KgEntity.label)))
        if query:
            needle = query.strip().lower()
            entities = [e for e in entities if needle in f"{e.label} {e.identifier or ''} {' '.join(e.aliases)}".lower()]
        return [self._entity_summary(e) for e in entities]

    def get_entity(self, entity_id: str) -> EntityDetail:
        entity = self.session.get(KgEntity, entity_id)
        if entity is None:
            raise NotFoundError(f"Entity '{entity_id}' was not found.", code="KG_ENTITY_NOT_FOUND")
        mentions = self.session.scalars(select(KgEntityMention).where(KgEntityMention.entity_id == entity.id))
        return EntityDetail(
            **self._entity_summary(entity).model_dump(),
            aliases=list(entity.aliases or []),
            candidates=list(entity.candidates or []),
            notes=list(entity.notes or []),
            type_fact_id=entity.type_fact_id,
            mentions=[
                MentionRead(
                    id=m.id,
                    origin=m.origin,
                    class_ref=m.class_ref,
                    identifier=m.identifier,
                    label=m.label,
                    reference_only=m.reference_only,
                    resolution_method=m.resolution_method,
                    document_id=m.document_id,
                    source=m.source,
                )
                for m in mentions
            ],
        )

    # ------------------------------------------------------------------ graph

    def _node(self, vertex: GraphVertex, ctx: _BuildContext) -> GraphNodeRead:
        properties: list[GraphPropertyRead] = []
        for key, value in vertex.properties.items():
            if key in ("identifier", "aliases"):
                continue
            prop_id, label = ctx.property_by_local_name.get(key, (None, key))
            properties.append(
                GraphPropertyRead(key=key, label=label, property_id=prop_id, values=value if isinstance(value, list) else [value])
            )
        entity = ctx.entity_by_vertex.get(vertex.id)
        return GraphNodeRead(
            id=vertex.id,
            label=vertex.label,
            name=vertex.name,
            class_id=vertex.class_id,
            class_label=ctx.view.class_label(vertex.class_id, vertex.label),
            identifier=vertex.properties.get("identifier"),
            entity_id=entity.id if entity else None,
            properties=properties,
            fact_count=len(vertex.fact_ids),
            source_ids=vertex.source_ids,
        )

    @staticmethod
    def _edge(edge: GraphEdge, ctx: _BuildContext) -> GraphEdgeRead:
        return GraphEdgeRead(
            id=edge.id,
            label=edge.label,
            predicate_id=edge.predicate_id,
            predicate_label=ctx.view.property_label(edge.predicate_id, edge.label),
            source=edge.out_id,
            target=edge.in_id,
            fact_count=len(edge.fact_ids),
            source_ids=edge.source_ids,
        )

    def _source_names(self, ids: set[str], ctx: _BuildContext) -> dict[str, str]:
        names = {s["id"]: s["filename"] for s in (ctx.build.config_snapshot or {}).get("sources", [])}
        return {i: names.get(i, i) for i in ids}

    def graph(
        self,
        build_id: str,
        *,
        class_ids: list[str] | None = None,
        predicate_ids: list[str] | None = None,
        source_ids: list[str] | None = None,
        limit: int = 500,
        via: GraphSource | None = None,
    ) -> GraphRead:
        ctx = self._context(build_id)
        store = via.store if via else self.store
        data = store.fetch_graph(build_id, limit=5000)
        class_counts = Counter(v.class_id for v in data.vertices)
        predicate_counts = Counter(e.predicate_id for e in data.edges)
        source_counts: Counter[str] = Counter()
        for element in [*data.vertices, *data.edges]:
            source_counts.update(set(element.source_ids))
        vertices = data.vertices
        if class_ids:
            vertices = [v for v in vertices if v.class_id in class_ids]
        if source_ids:
            vertices = [v for v in vertices if set(v.source_ids) & set(source_ids)]
        truncated = data.truncated or len(vertices) > limit
        vertices = vertices[:limit]
        kept = {v.id for v in vertices}
        edges = [e for e in data.edges if e.out_id in kept and e.in_id in kept]
        if predicate_ids:
            edges = [e for e in edges if e.predicate_id in predicate_ids]
        if source_ids:
            edges = [e for e in edges if set(e.source_ids) & set(source_ids)]
        total_nodes, total_edges = store.counts(build_id)
        names = self._source_names(set(source_counts), ctx)
        return GraphRead(
            build_id=build_id,
            build_number=ctx.build.number,
            ontology_version=ctx.build.ontology_version,
            graph_store=via.label if via else ctx.build.graph_store,
            deployment_id=via.deployment_id if via else None,
            read_warnings=via.warnings if via else [],
            nodes=[self._node(v, ctx) for v in vertices],
            edges=[self._edge(e, ctx) for e in edges],
            truncated=truncated,
            total_nodes=total_nodes,
            total_edges=total_edges,
            classes=sorted(
                (FacetCount(id=c, label=ctx.view.class_label(c, c), count=n) for c, n in class_counts.items()),
                key=lambda f: f.label,
            ),
            predicates=sorted(
                (FacetCount(id=p, label=ctx.view.property_label(p, p), count=n) for p, n in predicate_counts.items()),
                key=lambda f: f.label,
            ),
            sources=sorted(
                (FacetCount(id=s, label=names.get(s, s), count=n) for s, n in source_counts.items()), key=lambda f: f.label
            ),
        )

    def search(
        self, build_id: str, text: str, class_id: str | None = None, limit: int = 20, via: GraphSource | None = None
    ) -> list[GraphNodeRead]:
        ctx = self._context(build_id)
        store = via.store if via else self.store
        label = ctx.view.classes[class_id].local_name if class_id and class_id in ctx.view.classes else None
        return [self._node(v, ctx) for v in store.search_vertices(build_id, text, label=label, limit=limit)]

    def neighborhood(self, build_id: str, vertex_id: str, depth: int = 1, via: GraphSource | None = None) -> GraphRead:
        ctx = self._context(build_id)
        store = via.store if via else self.store
        data = store.neighborhood(build_id, vertex_id, depth=depth, limit=200)
        if not data.vertices:
            raise NotFoundError(f"Node '{vertex_id}' is not in build #{ctx.build.number}.", code="GRAPH_NODE_NOT_FOUND")
        total_nodes, total_edges = store.counts(build_id)
        return GraphRead(
            build_id=build_id,
            build_number=ctx.build.number,
            ontology_version=ctx.build.ontology_version,
            graph_store=via.label if via else ctx.build.graph_store,
            deployment_id=via.deployment_id if via else None,
            read_warnings=via.warnings if via else [],
            nodes=[self._node(v, ctx) for v in data.vertices],
            edges=[self._edge(e, ctx) for e in data.edges],
            truncated=data.truncated,
            total_nodes=total_nodes,
            total_edges=total_edges,
            classes=[],
            predicates=[],
            sources=[],
        )

    def _facts_by_ids(self, ids: list[str], ctx: _BuildContext, *, by_sequence: bool = False) -> list[FactDetail]:
        if not ids:
            return []
        facts = {f.id: f for f in self.session.scalars(select(KgCandidateFact).where(KgCandidateFact.id.in_(ids)))}
        ordered = [facts[i] for i in ids if i in facts]
        if by_sequence:  # RDF targets do not keep provenance order; restore the canonical (kind, sequence) order
            ordered.sort(key=lambda f: (_KIND_RANK.get(f.kind, 3), f.sequence))
        return [self._fact_detail(f, ctx) for f in ordered]

    def element(self, build_id: str, element_id: str, via: GraphSource | None = None) -> GraphElementDetail:
        ctx = self._context(build_id)
        store = via.store if via else self.store
        common = {
            "build_id": build_id,
            "build_number": ctx.build.number,
            "ontology_version": ctx.build.ontology_version,
            "ontology_version_id": ctx.build.ontology_version_id,
            "project_id": ctx.build.project_id,
            "deployment_id": via.deployment_id if via else None,
        }
        reordered = via is not None
        vertex = store.get_vertex(build_id, element_id)
        if vertex is not None:
            edges = store.edges_of(build_id, vertex.id)
            neighbour_ids = {e.in_id if e.out_id == vertex.id else e.out_id for e in edges}
            neighbours = [n for n in (store.get_vertex(build_id, i) for i in sorted(neighbour_ids)) if n]
            return GraphElementDetail(
                kind="node",
                node=self._node(vertex, ctx),
                relationships=[self._edge(e, ctx) for e in edges],
                neighbours=[self._node(n, ctx) for n in neighbours],
                facts=self._facts_by_ids(store.provenance(build_id, vertex.id), ctx, by_sequence=reordered),
                **common,
            )
        edge = store.get_edge(build_id, element_id)
        if edge is None:
            raise NotFoundError(
                f"Graph element '{element_id}' is not in build #{ctx.build.number}.", code="GRAPH_ELEMENT_NOT_FOUND"
            )
        subject = store.get_vertex(build_id, edge.out_id)
        obj = store.get_vertex(build_id, edge.in_id)
        return GraphElementDetail(
            kind="edge",
            edge=self._edge(edge, ctx),
            subject=self._node(subject, ctx) if subject else None,
            object=self._node(obj, ctx) if obj else None,
            facts=self._facts_by_ids(store.provenance(build_id, edge.id), ctx, by_sequence=reordered),
            **common,
        )

    # ------------------------------------------------------------------ evaluation & gaps

    def evaluation(self, build_id: str) -> EvaluationRead:
        build = self.config.require_build(build_id)
        if not build.evaluation:
            raise NotFoundError(
                f"Build #{build.number} has no evaluation yet (status: {build.status}).", code="KG_EVALUATION_NOT_AVAILABLE"
            )
        return EvaluationRead(build_id=build.id, **build.evaluation)

    def gaps(self, build_id: str) -> list[GapRead]:
        self.config.require_build(build_id)
        gaps = list(
            self.session.scalars(
                select(KgOntologyGap)
                .where(KgOntologyGap.build_id == build_id)
                .order_by(KgOntologyGap.gap_type, KgOntologyGap.label)
            )
        )
        proposal_ids = {pid for g in gaps for pid in g.proposal_ids or []}
        proposals = {
            p.id: p for p in self.session.scalars(select(ChangeProposal).where(ChangeProposal.id.in_(proposal_ids)))
        }
        return [
            GapRead(
                id=g.id,
                build_id=g.build_id,
                gap_type=g.gap_type,  # type: ignore[arg-type]
                term=g.term,
                label=g.label,
                description=g.description,
                suggestion=g.suggestion or {},
                occurrences=g.occurrences,
                origins=list(g.origins or []),
                evidence=list(g.evidence or []),
                fact_ids=list(g.fact_ids or []),
                status=g.status,  # type: ignore[arg-type]
                proposals=[
                    GapProposalRef(id=p.id, title=p.title, status=p.status, proposal_type=p.proposal_type)
                    for p in (proposals.get(pid) for pid in g.proposal_ids or [])
                    if p is not None
                ],
            )
            for g in gaps
        ]

    # ------------------------------------------------------------------ comparison

    def compare(self, base_id: str, target_id: str) -> BuildComparison:
        base = self.config.require_build(base_id)
        target = self.config.require_build(target_id)
        base_graph = self.store.fetch_graph(base.id, limit=100_000)
        target_graph = self.store.fetch_graph(target.id, limit=100_000)

        def diff(old: dict[str, str], new: dict[str, str]) -> ElementDiff:
            added = sorted(set(new) - set(old))
            removed = sorted(set(old) - set(new))
            return ElementDiff(
                added=len(added),
                removed=len(removed),
                unchanged=len(set(old) & set(new)),
                added_items=[{"id": i, "label": new[i]} for i in added[:50]],
                removed_items=[{"id": i, "label": old[i]} for i in removed[:50]],
            )

        def node_labels(vertices: list[GraphVertex]) -> dict[str, str]:
            return {v.id: f"{v.name} ({v.label})" for v in vertices}

        def edge_labels(edges: list[GraphEdge], vertices: list[GraphVertex]) -> dict[str, str]:
            names = {v.id: v.name for v in vertices}
            return {e.id: f"{names.get(e.out_id, e.out_id)} → {e.label} → {names.get(e.in_id, e.in_id)}" for e in edges}

        def metrics(build: KgBuild) -> dict[str, dict[str, object]]:
            return {
                m["key"]: m for s in (build.evaluation or {}).get("sections", []) for m in s["metrics"]
            }

        base_metrics, target_metrics = metrics(base), metrics(target)
        keys = list(dict.fromkeys([*target_metrics, *base_metrics]))
        return BuildComparison(
            base=self.config._summary(base),
            target=self.config._summary(target),
            nodes=diff(node_labels(base_graph.vertices), node_labels(target_graph.vertices)),
            edges=diff(
                edge_labels(base_graph.edges, base_graph.vertices), edge_labels(target_graph.edges, target_graph.vertices)
            ),
            metrics=[
                MetricComparison(
                    key=k,
                    label=str((target_metrics.get(k) or base_metrics.get(k) or {}).get("label", k)),
                    unit=str((target_metrics.get(k) or base_metrics.get(k) or {}).get("unit", "count")),
                    base=base_metrics.get(k, {}).get("value"),  # type: ignore[arg-type]
                    target=target_metrics.get(k, {}).get("value"),  # type: ignore[arg-type]
                )
                for k in keys
            ],
        )


_SEVERITY_ORDER = ("Violation", "Warning", "Info")


def _shacl_status(fact: KgCandidateFact) -> str | None:
    if fact.lanes is None:
        return None
    severities = {r.get("severity") for r in (fact.lanes.get("shacl") or {}).get("results", [])}
    return next((s for s in _SEVERITY_ORDER if s in severities), "conforms")

