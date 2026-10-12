"""KG build orchestrator: a deterministic, staged workflow executed outside the HTTP request.

Builds created since Phase 4 run ten stages (SHACL validation after structural validation); builds
created earlier keep their nine recorded stages and the Phase 3 evaluation.

Every stage transition, count and log line is persisted on the build so the UI reports real
progress. The workflow never raises: failures are recorded on the stage and the build. Only
accepted facts reach the graph store, and only under this build's graph scope.
"""

import logging
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.ids import utcnow
from app.modules.activity.service import record_activity
from app.modules.discovery.alignment import normalize_term
from app.modules.discovery.grounding import ChunkRef
from app.modules.graph.projection import PropertyGraphProjection, project_property_graph
from app.modules.graph.store import GraphStore
from app.modules.kg.canonical import LLM, STRUCTURED, ExtractionResult, FactCandidate, GapCandidate
from app.modules.kg.connectors import StructuredSource, TextSource, is_structured, open_structured, open_text
from app.modules.kg.deployments import LOCAL_SQL_SPEC, deploy, spec_from_snapshot
from app.modules.kg.evaluation import compute_evaluation
from app.modules.kg.extraction import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    LLMExtractionResponse,
    LLMOutputNormalizer,
    PromptChunk,
    build_user_prompt,
    make_batches,
)
from app.modules.kg.mapping import MappingSpec, transform_records, validate_mapping
from app.modules.kg.models import KgBuild, KgBuildLog, KgCandidateFact, KgEntity, KgEntityMention, KgOntologyGap
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.policy import get_policy
from app.modules.kg.rdf_candidates import build_candidate_graph, run_lanes
from app.modules.kg.resolution import ResolutionResult, ResolvedEntity, resolve_entities
from app.modules.kg.validation import (
    ACCEPTED,
    Assessment,
    assess_attribute_structure,
    assess_entity_evidence,
    assess_entity_structure,
    assess_fact_evidence,
    assess_relationship_structure,
    quarantine_conflicts,
)
from app.modules.llm.provider import LLMError, LLMOutputError, LLMProvider, LLMUsage
from app.modules.registry.artifacts import ArtifactIntegrityError, FilesystemArtifactRepository, StoredArtifact
from app.modules.registry.models import OntologyVersion
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.semantics.graphs import parse_rdf
from app.modules.semantics.owl import ontology_iri_of, snapshot_to_owl
from app.modules.shacl.shapes import build_shapes_graph, index_shapes_graph
from app.modules.sources.models import SourceDocument

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
GraphStoreFactory = Callable[[Session], GraphStore]

STAGES: list[tuple[str, str]] = [
    ("source_loading", "Source loading"),
    ("content_parsing", "Content parsing"),
    ("entity_extraction", "Entity extraction"),
    ("relationship_extraction", "Relationship extraction"),
    ("entity_resolution", "Entity resolution"),
    ("structural_validation", "Structural validation"),
    ("shacl_validation", "SHACL validation"),
    ("evidence_validation", "Evidence validation"),
    ("graph_persistence", "Graph persistence"),
    ("evaluation", "Evaluation"),
]
ACTIVE_STATUSES = ("queued", "running")


def initial_stages() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": label,
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            "summary": "",
            "counts": {},
        }
        for key, label in STAGES
    ]


class StageFailure(Exception):
    pass


class BuildTracker:
    """Persists stage transitions, counts and logs using short, independent transactions."""

    def __init__(self, session_factory: SessionFactory, build_id: str) -> None:
        self.session_factory = session_factory
        self.build_id = build_id
        self.current: str | None = None
        self._started: dict[str, float] = {}

    def _update(self, mutate: Callable[[KgBuild], None]) -> None:
        with self.session_factory() as session:
            build = session.get(KgBuild, self.build_id)
            if build is None:
                return
            mutate(build)
            session.commit()

    @staticmethod
    def _set_stage(build: KgBuild, key: str, **values: Any) -> None:
        stages = deepcopy(build.stages)
        for stage in stages:
            if stage["key"] == key:
                stage.update(values)
        build.stages = stages

    def log(self, stage: str, message: str, level: str = "info", **details: Any) -> None:
        with self.session_factory() as session:
            session.add(KgBuildLog(build_id=self.build_id, stage=stage, level=level, message=message, details=details))
            session.commit()

    def start(self, key: str) -> None:
        self.current = key
        self._started[key] = time.perf_counter()

        def mutate(build: KgBuild) -> None:
            build.current_stage = key
            self._set_stage(build, key, status="running", started_at=utcnow().isoformat())

        self._update(mutate)

    def progress(self, key: str, summary: str, counts: dict[str, Any]) -> None:
        self._update(lambda build: self._set_stage(build, key, summary=summary, counts=counts))

    def complete(self, key: str, summary: str, counts: dict[str, Any] | None = None) -> None:
        elapsed = int((time.perf_counter() - self._started.get(key, time.perf_counter())) * 1000)
        self._update(
            lambda build: self._set_stage(
                build,
                key,
                status="completed",
                completed_at=utcnow().isoformat(),
                duration_ms=elapsed,
                summary=summary,
                counts=counts or {},
            )
        )
        self.log(key, summary, duration_ms=elapsed)

    def merge_stats(self, **values: Any) -> None:
        def mutate(build: KgBuild) -> None:
            build.stats = {**deepcopy(build.stats or {}), **values}

        self._update(mutate)

    def fail(self, message: str) -> None:
        key = self.current or STAGES[0][0]
        elapsed = int((time.perf_counter() - self._started.get(key, time.perf_counter())) * 1000)

        def mutate(build: KgBuild) -> None:
            stages = deepcopy(build.stages)
            failed_seen = False
            for stage in stages:
                if stage["key"] == key:
                    stage.update(status="failed", completed_at=utcnow().isoformat(), duration_ms=elapsed, summary=message[:500])
                    failed_seen = True
                elif failed_seen and stage["status"] == "pending":
                    stage["status"] = "skipped"
            build.stages = stages
            build.status = "failed"
            build.error = message[:2000]
            build.completed_at = utcnow()
            record_activity(
                session_of(build),
                project_id=build.project_id,
                ontology_id=build.ontology_id,
                event_type="kg.build_failed",
                summary=f"Knowledge graph build #{build.number} failed at {key.replace('_', ' ')}: {message[:160]}",
                details={"build_id": build.id},
            )

        self._update(mutate)
        self.log(key, message, level="error")


def session_of(instance: Any) -> Session:
    from sqlalchemy.orm import object_session

    session = object_session(instance)
    assert session is not None
    return session


def mark_interrupted_builds(session: Session) -> int:
    builds = list(session.scalars(select(KgBuild).where(KgBuild.status.in_(ACTIVE_STATUSES))))
    for build in builds:
        stages = deepcopy(build.stages)
        for stage in stages:
            if stage["status"] == "running":
                stage["status"] = "failed"
                stage["summary"] = "Interrupted: the server stopped during this stage."
            elif stage["status"] == "pending":
                stage["status"] = "skipped"
        build.stages = stages
        build.status = "failed"
        build.error = "Interrupted: the server stopped before the build finished."
        build.completed_at = utcnow()
        session.add(
            KgBuildLog(build_id=build.id, stage=build.current_stage or STAGES[0][0], level="error", message=build.error)
        )
    session.commit()
    return len(builds)


def execute_kg_build(
    session_factory: SessionFactory,
    provider: LLMProvider | None,
    settings: Settings,
    graph_store_factory: GraphStoreFactory,
    build_id: str,
) -> None:
    """Background job. Never raises; failures are recorded on the build."""
    tracker = BuildTracker(session_factory, build_id)
    try:
        _Run(session_factory, provider, settings, graph_store_factory, tracker).execute()
    except StageFailure as failure:
        tracker.fail(str(failure))
    except Exception as error:  # noqa: BLE001 - surfaced to the user via the build record
        logger.exception("KG build %s failed", build_id)
        tracker.fail(f"Unexpected error: {error}")


class _Run:
    def __init__(
        self,
        session_factory: SessionFactory,
        provider: LLMProvider | None,
        settings: Settings,
        graph_store_factory: GraphStoreFactory,
        tracker: BuildTracker,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.graph_store_factory = graph_store_factory
        self.tracker = tracker
        self.build_id = tracker.build_id
        self.view: OntologyView
        self.structured: list[tuple[dict[str, Any], StructuredSource]] = []
        self.texts: list[TextSource] = []
        self.chunks: list[ChunkRef] = []
        self.chunk_index: dict[str, int] = {}
        self.batches: list[list[ChunkRef]] = []
        self.extraction = ExtractionResult()
        self.normalizers: list[LLMOutputNormalizer] = []
        self.stats: dict[str, Any] = {}

    # ------------------------------------------------------------------ driver

    def execute(self) -> None:
        with self.session_factory() as session:
            build = session.get(KgBuild, self.build_id)
            if build is None or build.status != "queued":
                return
            build.status = "running"
            build.started_at = utcnow()
            self.config = deepcopy(build.config_snapshot or {})
            self.settings_values = dict(build.settings or {})
            self.version_id = build.ontology_version_id
            self.project_id = build.project_id
            self.ontology_id = build.ontology_id
            self.build_number = build.number
            self.stage_keys = {stage["key"] for stage in build.stages or []}
            session.commit()

        self.stage_source_loading()
        self.stage_content_parsing()
        self.stage_entity_extraction()
        self.stage_relationship_extraction()
        resolution = self.stage_entity_resolution()
        assessments = self.stage_structural_validation(resolution)
        if "shacl_validation" in self.stage_keys:
            self.stage_shacl_validation(resolution, assessments)
        self.stage_evidence_validation(resolution, assessments)
        self.stage_graph_persistence()
        self.stage_evaluation()

    # ------------------------------------------------------------------ 1. source loading

    def stage_source_loading(self) -> None:
        key = "source_loading"
        self.tracker.start(key)
        with self.session_factory() as session:
            version = session.get(OntologyVersion, self.version_id)
            if version is None:
                raise StageFailure("The selected ontology version no longer exists.")
            self.view = OntologyView(
                OntologySnapshot.model_validate(version.snapshot), version_id=version.id, version=version.version
            )
            self.tracker.log(
                key,
                f"Schema authority: {self.view.name} {version.version} (published, immutable; "
                f"{len(self.view.classes)} classes, {len(self.view.object_properties)} relationships, "
                f"{len(self.view.datatype_properties)} attributes).",
            )
            mappings = {m["document_id"]: m for m in self.config.get("mappings", [])}
            for source in self.config.get("sources", []):
                document = session.get(SourceDocument, source["id"])
                if document is None:
                    raise StageFailure(f"Source '{source['filename']}' no longer exists.")
                if document.sha256 != source.get("sha256"):
                    raise StageFailure(f"Source '{document.filename}' changed after the build was configured.")
                if is_structured(document):
                    mapping = mappings.get(document.id)
                    if mapping is None:
                        raise StageFailure(f"Structured source '{document.filename}' has no mapping.")
                    self.structured.append((mapping, open_structured(session, document)))
                    self.tracker.log(key, f"Loaded {document.filename} (structured) with mapping '{mapping['name']}'.")
                else:
                    self.texts.append(open_text(session, document))
                    pages = f", {document.page_count} page(s)" if document.page_count else ""
                    self.tracker.log(key, f"Loaded {document.filename} ({document.media_type}{pages}).")
        summary = (
            f"{len(self.structured)} structured and {len(self.texts)} document source(s) loaded against "
            f"{self.view.name} {self.view.version}."
        )
        self.tracker.complete(key, summary, {"structured_sources": len(self.structured), "documents": len(self.texts)})

    # ------------------------------------------------------------------ 2. content parsing

    def stage_content_parsing(self) -> None:
        key = "content_parsing"
        self.tracker.start(key)
        records = 0
        for mapping, source in self.structured:
            columns = source.columns()
            count = min(source.count(), self.settings.kg_max_records_per_source)
            records += count
            issues = validate_mapping(MappingSpec.model_validate(mapping["spec"]), columns, self.view)
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                raise StageFailure(f"Mapping '{mapping['name']}' is invalid for {source.source_name}: {errors[0].message}")
            for warning in (i for i in issues if i.severity == "warning"):
                self.tracker.log(key, f"{source.source_name}: {warning.message}", level="warning")
            self.tracker.log(key, f"{source.source_name}: {len(columns)} columns, {count} records.")

        all_chunks: list[ChunkRef] = []
        for text in self.texts:
            chunks = text.chunks()
            for chunk in chunks:
                self.chunk_index[chunk.id] = chunk.index
                all_chunks.append(
                    ChunkRef(
                        id=chunk.id,
                        label="",
                        document_id=text.source_id,
                        document_name=text.source_name,
                        page=chunk.page,
                        start_offset=chunk.start_offset,
                        text=chunk.text,
                    )
                )
            self.tracker.log(key, f"{text.source_name}: {len(chunks)} text chunk(s).")
        max_chunks = int(self.settings_values.get("max_chunks", 20))
        self.chunks = all_chunks[:max_chunks]
        if len(all_chunks) > max_chunks:
            self.tracker.log(
                key,
                f"Only the first {max_chunks} of {len(all_chunks)} chunks will be analysed (build setting).",
                level="warning",
            )
        self.batches = make_batches(self.chunks, int(self.settings_values.get("batch_chars", 6000)))
        self.stats["sources"] = {
            "structured": len(self.structured),
            "records": records,
            "documents": len(self.texts),
            "chunks_total": len(all_chunks),
            "chunks_analyzed": len(self.chunks),
        }
        self.tracker.merge_stats(sources=self.stats["sources"])
        self.tracker.complete(
            key,
            f"{records} record(s) parsed; {len(self.chunks)} of {len(all_chunks)} text chunk(s) prepared in "
            f"{len(self.batches)} LLM batch(es).",
            {"records": records, "chunks": len(self.chunks), "batches": len(self.batches)},
        )

    # ------------------------------------------------------------------ 3. entity extraction

    def stage_entity_extraction(self) -> None:
        key = "entity_extraction"
        self.tracker.start(key)
        structured_mentions = 0
        for mapping, source in self.structured:
            result, stats = transform_records(
                mapping_id=mapping["id"],
                mapping_name=mapping["name"],
                spec=MappingSpec.model_validate(mapping["spec"]),
                source=source,
                view=self.view,
                limit=self.settings.kg_max_records_per_source,
            )
            self.extraction.extend(result)
            structured_mentions += stats["mentions"]
            self.tracker.log(
                key,
                f"{source.source_name}: {stats['records']} record(s) → {stats['mentions']} entity mention(s) "
                f"by deterministic mapping (no LLM).",
            )

        llm_mentions, failed, usage = 0, 0, LLMUsage()
        outputs: list[dict[str, Any]] = []
        include_attributes = bool(self.settings_values.get("extract_attributes", True))
        instructions = str(self.settings_values.get("instructions", ""))
        if self.batches:
            if self.provider is None:
                raise StageFailure("Document sources require an LLM provider, but none is configured.")
            self.tracker.log(
                key,
                f"Ontology-guided extraction with {self.provider.name} / {self.provider.model} "
                f"(prompt {PROMPT_VERSION}). Each request returns entities and their relationships; "
                "relationships are normalised in the next stage.",
            )
        for number, batch in enumerate(self.batches, start=1):
            labeled = {f"C{i}": replace(chunk, label=f"C{i}") for i, chunk in enumerate(batch, start=1)}
            prompt = build_user_prompt(
                self.view,
                [PromptChunk(c.label, c.document_name, c.page, c.text) for c in labeled.values()],
                include_attributes=include_attributes,
                instructions=instructions,
            )
            self.tracker.progress(
                key,
                f"LLM batch {number} of {len(self.batches)} in progress.",
                {"batches_total": len(self.batches), "batches_completed": number - 1},
            )
            started = time.perf_counter()
            assert self.provider is not None
            try:
                result = self.provider.generate_structured(
                    system=SYSTEM_PROMPT, user=prompt, schema=LLMExtractionResponse, schema_name="kg_extraction"
                )
            except LLMOutputError as error:
                failed += 1
                outputs.append({"batch": number, "chunk_ids": [c.id for c in batch], "error": str(error)})
                self.tracker.log(key, f"Batch {number}: the model returned invalid output ({error}).", level="warning")
                continue
            except LLMError as error:
                raise StageFailure(f"LLM request failed: {error}") from error
            usage = usage + result.usage
            normalizer = LLMOutputNormalizer(self.view, labeled, self.chunks, self.chunk_index, number)
            normalizer.entities(result.value.entities)
            normalizer.response = result.value
            self.normalizers.append(normalizer)
            llm_mentions += len(normalizer.result.mentions)
            outputs.append(
                {
                    "batch": number,
                    "chunk_ids": [c.id for c in batch],
                    "documents": sorted({c.document_name for c in batch}),
                    "attempts": result.attempts,
                    "usage": {"prompt_tokens": result.usage.prompt_tokens, "completion_tokens": result.usage.completion_tokens},
                    "seconds": round(time.perf_counter() - started, 1),
                    "output": result.value.model_dump(mode="json"),
                }
            )
            self.tracker.log(
                key,
                f"Batch {number}/{len(self.batches)}: {len(result.value.entities)} entities, "
                f"{len(result.value.relationships)} relationships, {len(result.value.attributes)} attributes, "
                f"{len(result.value.unknown_concepts)} unknown concepts returned "
                f"({time.perf_counter() - started:.1f} s).",
            )
        if self.batches and failed == len(self.batches):
            raise StageFailure("The model returned invalid output for every extraction batch.")
        for normalizer in self.normalizers:
            self.extraction.mentions += normalizer.result.mentions

        extraction_stats = {
            "batches": len(self.batches),
            "batches_completed": len(self.batches) - failed,
            "batches_failed": failed,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }
        self.stats["extraction"] = extraction_stats

        def mutate(build: KgBuild) -> None:
            build.llm_outputs = outputs
            build.stats = {**deepcopy(build.stats or {}), "extraction": extraction_stats}

        self.tracker._update(mutate)
        self.tracker.complete(
            key,
            f"{structured_mentions} structured and {llm_mentions} text entity mention(s) extracted"
            + (f"; {failed} LLM batch(es) returned invalid output" if failed else "")
            + ".",
            {"structured_mentions": structured_mentions, "text_mentions": llm_mentions, **extraction_stats},
        )

    # ------------------------------------------------------------------ 4. relationship extraction

    def stage_relationship_extraction(self) -> None:
        key = "relationship_extraction"
        self.tracker.start(key)
        include_attributes = bool(self.settings_values.get("extract_attributes", True))
        for normalizer in self.normalizers:
            response = normalizer.response
            assert response is not None
            before_facts = len(normalizer.result.facts)
            normalizer.relationships(response.relationships)
            if include_attributes:
                normalizer.attributes(response.attributes)
            normalizer.unknown(response.unknown_concepts)
            self.extraction.facts += normalizer.result.facts[before_facts:]
            self.extraction.gaps += normalizer.result.gaps
            self.extraction.discarded += normalizer.result.discarded
        relationships = [f for f in self.extraction.facts if f.kind == "relationship"]
        attributes = [f for f in self.extraction.facts if f.kind == "attribute"]
        unresolved = sum(1 for f in self.extraction.facts if f.predicate_id is None)
        for item in self.extraction.discarded:
            self.tracker.log(key, f"Discarded {item['item']}: {item['reason']}", level="warning")
        counts = {
            "relationship_candidates": len(relationships),
            "attribute_candidates": len(attributes),
            "structured_relationships": sum(1 for f in relationships if f.origin == STRUCTURED),
            "text_relationships": sum(1 for f in relationships if f.origin != STRUCTURED),
            "unresolved_predicates": unresolved,
            "gap_candidates": len(self.extraction.gaps),
            "discarded": len(self.extraction.discarded),
        }
        self.tracker.complete(
            key,
            f"{len(relationships)} relationship and {len(attributes)} attribute candidate(s); {unresolved} use a "
            f"predicate not defined in {self.view.version}; {len(self.extraction.gaps)} gap candidate(s).",
            counts,
        )

    # ------------------------------------------------------------------ 5. entity resolution

    def stage_entity_resolution(self) -> ResolutionResult:
        key = "entity_resolution"
        self.tracker.start(key)
        resolution = resolve_entities(self.extraction.mentions, self.view)
        stats = resolution.stats()
        self.stats["resolution"] = stats
        mention_by_key = {m.key: m for m in self.extraction.mentions}
        self.entity_rows: dict[str, KgEntity] = {}
        with self.session_factory() as session:
            for entity in resolution.entities.values():
                row = KgEntity(
                    build_id=self.build_id,
                    vertex_id=entity.vertex_id,
                    class_id=entity.class_id,
                    class_ref=entity.class_ref[:300],
                    class_label=self.view.class_label(entity.class_id, entity.class_ref)[:300],
                    identifier=(entity.identifier or None) and entity.identifier[:300],
                    key_namespace=entity.key_namespace,
                    label=entity.label[:500],
                    aliases=entity.aliases[:20],
                    resolution_method=entity.method,
                    ambiguous=entity.ambiguous,
                    candidates=entity.candidates,
                    notes=entity.notes[:20],
                    has_master_record=entity.has_master_record,
                    mention_count=len(entity.mentions),
                    status="pending",
                )
                session.add(row)
                session.flush()
                self.entity_rows[entity.vertex_id] = row
                for mention in entity.mentions:
                    session.add(
                        KgEntityMention(
                            build_id=self.build_id,
                            entity_id=row.id,
                            origin=mention.origin,
                            class_ref=mention.class_ref[:300],
                            identifier=(mention.identifier or None) and mention.identifier[:300],
                            label=(mention.label or None) and mention.label[:500],
                            reference_only=mention.reference_only,
                            resolution_method=resolution.mention_method.get(mention.key, entity.method),
                            document_id=mention.source.document_id or None,
                            source=mention.source.as_dict(),
                        )
                    )
            session.commit()
        self.mention_by_key = mention_by_key
        self.tracker.merge_stats(resolution=stats)
        self.tracker.complete(
            key,
            f"{stats['mentions']} mention(s) resolved to {stats['entities']} entities "
            f"({stats['merged_mentions']} merged, {stats['ambiguous_entities']} ambiguous, "
            f"{stats['unresolved_class_entities']} of undefined classes).",
            stats,
        )
        return resolution

    # ------------------------------------------------------------------ 6. structural validation

    def stage_structural_validation(
        self, resolution: ResolutionResult
    ) -> dict[str, tuple[Assessment, ResolvedEntity | None, ResolvedEntity | None]]:
        key = "structural_validation"
        self.tracker.start(key)
        self.entity_assessments: dict[str, Assessment] = {
            vertex_id: assess_entity_structure(entity, self.view) for vertex_id, entity in resolution.entities.items()
        }
        fact_assessments: dict[str, tuple[Assessment, ResolvedEntity | None, ResolvedEntity | None]] = {}
        for fact in self.extraction.facts:
            subject = resolution.entity_of(fact.subject)
            obj = resolution.entity_of(fact.object)
            if fact.kind == "relationship":
                assessment = assess_relationship_structure(fact, subject, obj, self.view)
            else:
                assessment = assess_attribute_structure(fact, subject, self.view)
            fact_assessments[fact.key] = (assessment, subject, obj)
        all_assessments = list(self.entity_assessments.values()) + [a for a, _, _ in fact_assessments.values()]
        failed = sum(1 for a in all_assessments if not all(c.passed for c in a.structural))
        codes: dict[str, int] = {}
        for assessment in all_assessments:
            for check in assessment.structural:
                if not check.passed:
                    codes[check.code] = codes.get(check.code, 0) + 1
        for code, count in sorted(codes.items(), key=lambda item: -item[1]):
            self.tracker.log(key, f"{count} fact(s) failed structural check '{code}'.", level="warning")
        self.tracker.complete(
            key,
            f"{len(all_assessments) - failed} of {len(all_assessments)} candidate fact(s) are structurally valid; "
            f"{failed} failed (they will be rejected).",
            {"checked": len(all_assessments), "passed": len(all_assessments) - failed, "failed": failed, **codes},
        )
        return fact_assessments

    # ------------------------------------------------------------------ 7. SHACL validation (Phase 4)

    def stage_shacl_validation(
        self,
        resolution: ResolutionResult,
        fact_assessments: dict[str, tuple[Assessment, ResolvedEntity | None, ResolvedEntity | None]],
    ) -> None:
        key = "shacl_validation"
        self.tracker.start(key)
        policy = get_policy(self.settings_values.get("validation_policy"))
        snapshot = self.view.snapshot.with_iris()
        with self.session_factory() as session:
            version = session.get(OntologyVersion, self.version_id)
            assert version is not None
            artifacts = dict(version.artifacts or {})
        if "shapes" in artifacts:
            stored = StoredArtifact(**artifacts["shapes"])
            try:
                content = FilesystemArtifactRepository(self.settings.artifact_dir).read(stored)
            except ArtifactIntegrityError as error:
                raise StageFailure(f"The version's SHACL shapes failed their integrity check: {error}") from error
            shapes = parse_rdf(content, "turtle")
            index = index_shapes_graph(shapes, snapshot)
            source = f"version package ({stored.filename}, sha256 {stored.sha256[:12]})"
        else:
            shapes, index = build_shapes_graph(snapshot)
            source = "derived at build time from the published snapshot (the version predates SHACL packages)"
        data_namespace = self.config.get("data_namespace") or f"{ontology_iri_of(snapshot)}/data/"
        candidate = build_candidate_graph(
            self.view, resolution, self.extraction.facts, fact_assessments, data_namespace
        )
        self.tracker.log(
            key,
            f"Policy {policy.id} ({policy.name}). Shapes: {source}; {len(candidate.graph)} asserted candidate "
            f"triple(s) under {data_namespace}e/. Inference: none.",
        )
        lanes = run_lanes(
            view=self.view,
            policy=policy,
            candidate=candidate,
            shapes=shapes,
            index=index,
            ontology=snapshot_to_owl(snapshot, include_axioms=False),
            shapes_source=source,
            entity_assessments=self.entity_assessments,
            fact_items={f.key: (f, *fact_assessments[f.key]) for f in self.extraction.facts},
        )
        report = lanes.as_dict()
        for message in lanes.inconsistencies[:20]:
            self.tracker.log(key, f"OWL 2 RL inconsistency: {message}", level="warning")
        if lanes.unmapped_results:
            self.tracker.log(key, f"{lanes.unmapped_results} SHACL result(s) could not be attributed to a fact.", level="warning")
        self.stats["shacl"] = {**report, "policy": policy.id, "data_namespace": data_namespace, "data_triples": len(candidate.graph)}
        self.tracker.merge_stats(shacl=self.stats["shacl"], policy=policy.config())
        severity = report["by_severity"]
        outcomes = report["by_outcome"]
        self.tracker.complete(
            key,
            f"{report['results']} SHACL result(s) ({severity.get('Violation', 0)} violation, "
            f"{severity.get('Warning', 0)} warning, {severity.get('Info', 0)} info) from {report['shapes_used']} "
            f"shape(s); under {policy.id}: {outcomes.get('reject', 0)} reject, {outcomes.get('quarantine', 0)} "
            f"quarantine, {outcomes.get('warn', 0)} warn, {outcomes.get('info', 0)} info."
            + (f" {len(lanes.inconsistencies)} OWL 2 RL inconsistenc(y/ies)." if policy.entailment else ""),
            {
                "results": report["results"],
                **{f"severity_{k.lower()}": v for k, v in severity.items()},
                **{f"outcome_{k}": v for k, v in outcomes.items()},
                "data_triples": len(candidate.graph),
            },
        )

    # ------------------------------------------------------------------ 8. evidence validation

    def stage_evidence_validation(
        self,
        resolution: ResolutionResult,
        fact_assessments: dict[str, tuple[Assessment, ResolvedEntity | None, ResolvedEntity | None]],
    ) -> None:
        key = "evidence_validation"
        self.tracker.start(key)
        for vertex_id, entity in resolution.entities.items():
            assess_entity_evidence(self.entity_assessments[vertex_id], entity)
        for fact in self.extraction.facts:
            assessment, subject, obj = fact_assessments[fact.key]
            assess_fact_evidence(
                assessment,
                fact,
                subject=subject,
                obj=obj,
                subject_mention=self.mention_by_key.get(fact.subject or ""),
                object_mention=self.mention_by_key.get(fact.object or ""),
                entity_status=self.entity_assessments,
                view=self.view,
            )
        conflicts = quarantine_conflicts(
            [(f, fact_assessments[f.key][0], fact_assessments[f.key][1]) for f in self.extraction.facts if f.kind == "attribute"],
            self.view,
        )

        evidence_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        self.fact_ids_by_key: dict[str, str] = {}
        with self.session_factory() as session:
            sequence = 0
            for vertex_id, entity in resolution.entities.items():
                assessment = self.entity_assessments[vertex_id]
                sequence += 1
                row = self.entity_rows[vertex_id]
                fact = KgCandidateFact(
                    build_id=self.build_id,
                    sequence=sequence,
                    kind="type",
                    origin=STRUCTURED if any(m.origin == STRUCTURED for m in entity.mentions) else LLM,
                    status=assessment.status,
                    subject_entity_id=row.id,
                    subject_label=entity.label[:500],
                    subject_class_id=entity.class_id,
                    predicate_id=entity.class_id,
                    predicate_ref="rdf:type",
                    predicate_label="is a",
                    object_label=self.view.class_label(entity.class_id, entity.class_ref)[:500],
                    structural=assessment.structural_dict(),
                    evidence=assessment.evidence_dict(),
                    resolution=assessment.resolution_dict(),
                    reasons=assessment.reasons,
                    lanes=assessment.lanes_dict(),
                    sources=[m.source.as_dict() for m in entity.mentions][:20],
                    document_ids=sorted({m.source.document_id for m in entity.mentions if m.source.document_id}),
                )
                session.add(fact)
                session.flush()
                entity_row = session.get(KgEntity, row.id)
                assert entity_row is not None
                entity_row.status = assessment.status
                entity_row.type_fact_id = fact.id
                evidence_counts[assessment.evidence_status] = evidence_counts.get(assessment.evidence_status, 0) + 1
                status_counts[assessment.status] = status_counts.get(assessment.status, 0) + 1
            for candidate in self.extraction.facts:
                assessment, subject, obj = fact_assessments[candidate.key]
                sequence += 1
                fact = self._fact_row(candidate, assessment, subject, obj, sequence)
                session.add(fact)
                session.flush()
                self.fact_ids_by_key[candidate.key] = fact.id
                evidence_counts[assessment.evidence_status] = evidence_counts.get(assessment.evidence_status, 0) + 1
                status_counts[assessment.status] = status_counts.get(assessment.status, 0) + 1
            session.commit()

        self.stats["facts"] = {"by_status": status_counts, "by_evidence": evidence_counts, "conflicts": conflicts}
        self.tracker.merge_stats(facts=self.stats["facts"])
        self.tracker.complete(
            key,
            f"Evidence: {evidence_counts.get('supported', 0)} supported, {evidence_counts.get('weak', 0)} weak, "
            f"{evidence_counts.get('unlocated', 0)} not located, {evidence_counts.get('missing', 0)} missing. "
            f"Outcome: {status_counts.get('accepted', 0)} accepted, {status_counts.get('rejected', 0)} rejected, "
            f"{status_counts.get('quarantined', 0)} quarantined.",
            {**{f"evidence_{k}": v for k, v in evidence_counts.items()}, **status_counts, "conflicts": conflicts},
        )

    def _fact_row(
        self,
        candidate: FactCandidate,
        assessment: Assessment,
        subject: ResolvedEntity | None,
        obj: ResolvedEntity | None,
        sequence: int,
    ) -> KgCandidateFact:
        subject_row = self.entity_rows.get(subject.vertex_id) if subject else None
        object_row = self.entity_rows.get(obj.vertex_id) if obj else None
        is_attribute = candidate.kind == "attribute"
        prop = (self.view.datatype_properties if is_attribute else self.view.object_properties).get(
            candidate.predicate_id or ""
        )
        value = None
        datatype = None
        if is_attribute:
            value = assessment.canonical_value if assessment.canonical_value is not None else candidate.value
            datatype = prop.datatype.value if prop is not None else None
        return KgCandidateFact(
            build_id=self.build_id,
            sequence=sequence,
            kind=candidate.kind,
            origin=candidate.origin,
            status=assessment.status,
            subject_entity_id=subject_row.id if subject_row else None,
            subject_label=(subject.label if subject else (candidate.subject_ref or "?"))[:500],
            subject_class_id=subject.class_id if subject else None,
            predicate_id=candidate.predicate_id,
            predicate_ref=candidate.predicate_ref[:300],
            predicate_label=(prop.label if prop else candidate.predicate_ref)[:300],
            object_entity_id=object_row.id if object_row else None,
            object_label=(obj.label if obj else (candidate.object_ref or ""))[:500] if not is_attribute else "",
            object_class_id=obj.class_id if obj else None,
            value=value,
            datatype=datatype,
            structural=assessment.structural_dict(),
            evidence=assessment.evidence_dict(),
            resolution=assessment.resolution_dict(),
            reasons=assessment.reasons,
            lanes=assessment.lanes_dict(),
            sources=[candidate.source.as_dict()],
            document_ids=[candidate.source.document_id] if candidate.source.document_id else [],
        )

    # ------------------------------------------------------------------ 9. graph persistence

    def stage_graph_persistence(self) -> None:
        key = "graph_persistence"
        self.tracker.start(key)
        snapshot = self.view.snapshot
        data_namespace = self.config.get("data_namespace") or f"{ontology_iri_of(snapshot.with_iris())}/data/"
        with self.session_factory() as session:
            store = self.graph_store_factory(session)
            facts = list(
                session.scalars(
                    select(KgCandidateFact)
                    .where(KgCandidateFact.build_id == self.build_id, KgCandidateFact.status == ACCEPTED)
                    .order_by(KgCandidateFact.sequence)
                )
            )
            entities = {
                e.id: e for e in session.scalars(select(KgEntity).where(KgEntity.build_id == self.build_id))
            }
            projection = project_property_graph(self.view, facts, entities)
            for fact in facts:
                element = projection.element_of_fact.get(fact.id)
                if element is not None:
                    fact.graph_element_id = element
            build = session.get(KgBuild, self.build_id)
            assert build is not None
            canonical = deploy(
                session,
                build=build,
                spec=LOCAL_SQL_SPEC,
                snapshot=snapshot,
                projection=projection,
                data_namespace=data_namespace,
                oxigraph_dir=self.settings.oxigraph_dir,
                sql_store=store,
                origin="build",
                requested_by=build.requested_by,
            )
            if canonical.status != "completed":
                raise StageFailure(f"The canonical graph store write failed: {canonical.error}")
            build.graph_store = store.name
            session.commit()
            node_count, edge_count = store.counts(self.build_id)
        if projection.skipped_relationships:
            self.tracker.log(
                key,
                f"{projection.skipped_relationships} accepted relationship(s) skipped: an endpoint is not a graph node.",
                level="warning",
            )
        duplicate_facts = projection.merged_duplicate_facts
        deployments = [{"id": canonical.id, "target": LOCAL_SQL_SPEC.name, "kind": "local-sql", "status": "completed"}]
        target = self.config.get("graph_target") or {}
        note = ""
        if target.get("kind") and target["kind"] != "local-sql":
            outcome = self._deploy_to_target(key, target, snapshot, projection, data_namespace)
            deployments.append(outcome)
            note = (
                f" Deployed to {outcome['target']}: {outcome['summary']}, verified."
                if outcome["status"] == "completed"
                else f" Deployment to {outcome['target']} {outcome['status']}: {outcome.get('error') or outcome.get('reason')}"
            )
        self.stats["graph"] = {
            "nodes": node_count,
            "edges": edge_count,
            "store": store.name,
            "graph_id": self.build_id,
            "deployments": deployments,
        }
        self.tracker.merge_stats(graph=self.stats["graph"])
        self.tracker.complete(
            key,
            f"{node_count} node(s) and {edge_count} edge(s) written to the {store.name} graph store under this build's "
            f"graph scope ({duplicate_facts} duplicate relationship fact(s) merged into existing edges).{note}",
            {"nodes": node_count, "edges": edge_count, "merged_duplicate_facts": duplicate_facts},
        )

    def _deploy_to_target(
        self,
        key: str,
        target: dict[str, Any],
        snapshot: OntologySnapshot,
        projection: PropertyGraphProjection,
        data_namespace: str,
    ) -> dict[str, Any]:
        """Deploy to the build's selected target. A failing target never fails the build: the
        canonical graph is complete, and the outcome is recorded and can be retried."""
        name = target.get("name") or target.get("id", "")
        with self.session_factory() as session:
            build = session.get(KgBuild, self.build_id)
            assert build is not None
            try:
                row = deploy(
                    session,
                    build=build,
                    spec=spec_from_snapshot(target, self.settings.graph_allow_private_networks),
                    snapshot=snapshot,
                    projection=projection,
                    data_namespace=data_namespace,
                    oxigraph_dir=self.settings.oxigraph_dir,
                    sql_store=self.graph_store_factory(session),
                    origin="build",
                    requested_by=build.requested_by,
                )
            except DomainError as error:
                session.rollback()
                self.tracker.log(key, f"Not deployed to {name}: {error.message}", level="warning")
                return {"target": name, "kind": target.get("kind"), "status": "skipped", "reason": error.message}
            session.commit()
            stats = row.stats or {}
            summary = (
                f"{stats.get('triples', 0)} triple(s)"
                if row.data_model == "rdf"
                else f"{stats.get('vertices', 0)} vertices and {stats.get('edges', 0)} edges"
            )
            detail = f" in {len(row.graphs or {})} named graph(s)" if row.data_model == "rdf" else ""
            outcome = {
                "id": row.id,
                "target": row.target_name,
                "kind": row.target_kind,
                "status": row.status,
                "triples": stats.get("triples"),
                "summary": summary,
                "error": row.error,
            }
        if outcome["status"] == "completed":
            self.tracker.log(
                key,
                f"Deployed to {name} ({target.get('kind')}): {summary}{detail}, verified by reading the counts back.",
            )
        else:
            self.tracker.log(key, f"Deployment to {name} failed: {outcome['error']}", level="warning")
        return outcome

    # ------------------------------------------------------------------ 10. evaluation

    def _persist_gaps(self, session: Session) -> list[KgOntologyGap]:
        grouped: dict[str, tuple[GapCandidate, list[GapCandidate]]] = {}
        for gap in self.extraction.gaps:
            if gap.gap_type == "unmapped_field":
                key = f"unmapped_field|{gap.mapping_id}|{gap.column}"
            elif gap.gap_type == "unknown_class":
                key = f"unknown_class|{normalize_term(gap.label)}"
            else:
                key = "|".join(
                    [
                        gap.gap_type,
                        normalize_term(gap.label),
                        normalize_term(gap.domain_id or gap.domain_ref or ""),
                        normalize_term(gap.range_id or gap.range_ref or "") if gap.gap_type == "unknown_relationship" else "",
                    ]
                )
            if key in grouped:
                grouped[key][1].append(gap)
            else:
                grouped[key] = (gap, [gap])
        rows: list[KgOntologyGap] = []
        for key, (first, members) in grouped.items():
            evidence: list[dict[str, Any]] = []
            seen: set[str] = set()
            for member in members:
                ref = member.evidence.as_dict()
                identity = f"{ref.get('document_id')}|{ref.get('row_number')}|{ref.get('quote')}"
                if identity not in seen and len(evidence) < 5:
                    seen.add(identity)
                    evidence.append(ref)
            domain_id = first.domain_id or next((m.domain_id for m in members if m.domain_id), None)
            range_id = first.range_id or next((m.range_id for m in members if m.range_id), None)
            row = KgOntologyGap(
                build_id=self.build_id,
                gap_type=first.gap_type,
                gap_key=key[:400],
                term=first.term[:300],
                label=first.label[:300],
                description=first.description,
                suggestion={
                    "domain_ref": first.domain_ref,
                    "domain_id": domain_id,
                    "domain_label": self.view.class_label(domain_id, first.domain_ref or "") or None,
                    "range_ref": first.range_ref,
                    "range_id": range_id,
                    "range_label": self.view.class_label(range_id, first.range_ref or "") or None,
                    "datatype": first.datatype,
                    "column": first.column,
                    "mapping_id": first.mapping_id,
                    "sample_values": first.sample_values,
                    "definition": next((m.definition for m in members if m.definition), ""),
                },
                occurrences=sum(m.occurrences for m in members),
                origins=sorted({m.origin for m in members}),
                evidence=evidence,
                fact_ids=[self.fact_ids_by_key[m.fact_key] for m in members if m.fact_key in self.fact_ids_by_key],
                status="open",
                proposal_ids=[],
            )
            session.add(row)
            rows.append(row)
        session.flush()
        return rows

    def stage_evaluation(self) -> None:
        key = "evaluation"
        self.tracker.start(key)
        with self.session_factory() as session:
            gaps = self._persist_gaps(session)
            facts = list(session.scalars(select(KgCandidateFact).where(KgCandidateFact.build_id == self.build_id)))
            entities = list(session.scalars(select(KgEntity).where(KgEntity.build_id == self.build_id)))
            store = self.graph_store_factory(session)
            graph = store.fetch_graph(self.build_id, limit=100_000)
            unprovenanced = sum(1 for v in graph.vertices if not v.fact_ids) + sum(1 for e in graph.edges if not e.fact_ids)
            evaluation = compute_evaluation(
                view=self.view,
                facts=facts,
                entities=entities,
                gaps=gaps,
                stats=self.stats,
                graph_counts=store.counts(self.build_id),
                unprovenanced_graph_elements=unprovenanced,
            )
            build = session.get(KgBuild, self.build_id)
            assert build is not None
            build.evaluation = evaluation
            build.stats = {**deepcopy(build.stats or {}), **self.stats, "gaps": len(gaps)}
            build.status = "completed"
            build.current_stage = None
            build.completed_at = utcnow()
            elapsed = int((time.perf_counter() - self.tracker._started.get(key, time.perf_counter())) * 1000)
            stages = deepcopy(build.stages)
            for stage in stages:
                if stage["key"] == key:
                    stage.update(
                        status="completed",
                        completed_at=utcnow().isoformat(),
                        duration_ms=elapsed,
                        summary=f"Quality indicators computed; {len(gaps)} ontology gap(s) identified.",
                        counts={"gaps": len(gaps), "metrics": sum(len(s["metrics"]) for s in evaluation["sections"])},
                    )
            build.stages = stages
            counts = evaluation["status_counts"]
            record_activity(
                session,
                project_id=self.project_id,
                ontology_id=self.ontology_id,
                event_type="kg.build_completed",
                summary=f"Knowledge graph build #{self.build_number} completed against {self.view.version}: "
                f"{counts.get('accepted', 0)} accepted, {counts.get('rejected', 0)} rejected, "
                f"{counts.get('quarantined', 0)} quarantined facts; {len(gaps)} ontology gap(s)",
                details={"build_id": self.build_id},
            )
            session.add(
                KgBuildLog(
                    build_id=self.build_id,
                    stage=key,
                    level="info",
                    message=f"Quality indicators computed; {len(gaps)} ontology gap(s) identified. Build completed.",
                    details={"duration_ms": elapsed},
                )
            )
            session.commit()
