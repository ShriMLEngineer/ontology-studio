"""Deterministic ontology alignment of grounded LLM findings.

The LLM suggests an action; alignment checks it against the baseline ontology so that proposals
reuse existing concepts, avoid duplicates and surface semantic conflicts. Every adjustment is
recorded as a note that reviewers can see.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.core.ids import new_element_id
from app.modules.discovery.contract import LLMFinding
from app.modules.discovery.grounding import GroundedEvidence
from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
    to_class_local_name,
    to_property_local_name,
)

AnyElement = ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition

SIMILAR_THRESHOLD = 0.85
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NOUNS = {"class": "class", "object_property": "relationship", "datatype_property": "attribute"}
_ID_PREFIX = {"class": "cls", "object_property": "op", "datatype_property": "dp"}
_LITERAL_TYPES = {
    "string": "string", "text": "string", "str": "string", "xsd string": "string",
    "integer": "integer", "int": "integer", "xsd integer": "integer",
    "decimal": "decimal", "float": "decimal", "double": "decimal", "number": "decimal",
    "money": "decimal", "currency": "decimal", "amount": "decimal", "xsd decimal": "decimal",
    "boolean": "boolean", "bool": "boolean", "xsd boolean": "boolean",
    "date": "date", "xsd date": "date",
    "datetime": "dateTime", "date time": "dateTime", "timestamp": "dateTime", "xsd datetime": "dateTime",
    "uri": "anyURI", "url": "anyURI", "anyuri": "anyURI", "any uri": "anyURI", "xsd anyuri": "anyURI",
}


def literal_datatype(ref: str | None) -> str | None:
    """Map a range such as 'string' or 'xsd:date' to a supported XSD datatype, if it is one."""
    if not ref:
        return None
    return _LITERAL_TYPES.get(" ".join(re.findall(r"[a-z]+", ref.lower())))


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_term(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", _CAMEL.sub(" ", text).lower())
    return " ".join(_singular(w) for w in words)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return max(ratio, jaccard)


def element_kind(element: AnyElement) -> str:
    if isinstance(element, ClassDefinition):
        return "class"
    if isinstance(element, ObjectPropertyDefinition):
        return "object_property"
    return "datatype_property"


@dataclass(frozen=True)
class Match:
    element_id: str
    element_kind: str
    label: str
    score: float
    match_type: str  # exact | alias | similar
    matched_name: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "label": self.label,
            "score": round(self.score, 3),
            "match_type": self.match_type,
            "matched_name": self.matched_name,
        }


class ElementIndex:
    def __init__(self, schema: OntologySchema) -> None:
        self.elements: dict[str, AnyElement] = {
            e.id: e for e in (*schema.classes, *schema.object_properties, *schema.datatype_properties)
        }
        self.local_names = {e.local_name for e in self.elements.values()}

    def get(self, element_id: str | None) -> AnyElement | None:
        return self.elements.get(element_id) if element_id else None

    def names(self, element: AnyElement) -> list[tuple[str, str]]:
        return [
            (normalize_term(element.label), "exact"),
            (normalize_term(element.local_name), "exact"),
            *((normalize_term(a), "alias") for a in element.aliases),
        ]

    def match(self, terms: list[str], kind: str | None) -> list[Match]:
        normalized = [n for n in {normalize_term(t) for t in terms if t} if n]
        best: dict[str, Match] = {}
        for element in self.elements.values():
            ekind = element_kind(element)
            if kind and ekind != kind:
                continue
            for name, name_type in self.names(element):
                for term in normalized:
                    score = 1.0 if term == name else similarity(term, name)
                    match_type = name_type if score == 1.0 else "similar"
                    current = best.get(element.id)
                    if score >= 0.75 and (current is None or score > current.score):
                        best[element.id] = Match(element.id, ekind, element.label, score, match_type, name)
        return sorted(best.values(), key=lambda m: (-m.score, m.label))[:3]

    def exact(self, terms: list[str], kind: str | None) -> Match | None:
        return next((m for m in self.match(terms, kind) if m.match_type in {"exact", "alias"}), None)


@dataclass
class ProposalDraft:
    key: str
    proposal_type: str
    element_kind: str
    term: str
    title: str
    rationale: str
    confidence: float
    target_element_id: str | None
    new_element: dict[str, Any] | None
    changes: dict[str, dict[str, Any]]
    alignment: dict[str, Any]
    depends_on: list[str]
    evidence: list[GroundedEvidence]
    llm_output: dict[str, Any]


@dataclass(frozen=True)
class Discard:
    term: str
    action: str
    element_kind: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"term": self.term, "action": self.action, "element_kind": self.element_kind, "reason": self.reason}


@dataclass
class AlignmentResult:
    proposals: list[ProposalDraft] = field(default_factory=list)
    discarded: list[Discard] = field(default_factory=list)


def make_title(proposal_type: str, kind: str, label: str, alias: str | None = None) -> str:
    noun = _NOUNS[kind]
    return {
        "add": f"Add {noun} '{label}'",
        "reuse": f"Reuse existing {noun} '{label}'",
        "alias": f"Add alias '{alias}' to {noun} '{label}'",
        "modify": f"Modify {noun} '{label}'",
        "conflict": f"Resolve conflict on {noun} '{label}'",
    }[proposal_type][:300]


class _Aligner:
    def __init__(self, schema: OntologySchema) -> None:
        self.index = ElementIndex(schema)
        self.result = AlignmentResult()
        self.used_local_names = set(self.index.local_names)
        self.added_classes: dict[str, ProposalDraft] = {}

    # -- references -----------------------------------------------------------------------------

    def resolve_class(self, ref: str | None, notes: list[str], role: str) -> tuple[str | None, str | None]:
        """Resolve a class reference to (class id, dependency draft key)."""
        if not ref:
            return None, None
        element = self.index.get(ref)
        if element is not None and element_kind(element) == "class":
            return element.id, None
        exact = self.index.exact([ref], "class")
        if exact:
            return exact.element_id, None
        draft = self.added_classes.get(normalize_term(ref))
        if draft and draft.new_element:
            return draft.new_element["id"], draft.key
        notes.append(f"{role.capitalize()} class '{ref}' could not be resolved; choose one before approving.")
        return None, None

    def unique_local_name(self, base: str) -> str:
        candidate, counter = base, 2
        while candidate in self.used_local_names:
            candidate, counter = f"{base}{counter}", counter + 1
        self.used_local_names.add(candidate)
        return candidate

    # -- main -----------------------------------------------------------------------------------

    def align(self, finding: LLMFinding, evidence: list[GroundedEvidence]) -> None:
        notes: list[str] = []
        original = finding
        datatype = literal_datatype(finding.range) if finding.element_kind == "object_property" else None
        if datatype and finding.action in {"add", "modify"}:
            notes.append(
                f"Range '{finding.range}' is a literal datatype, so this was converted from a relationship to an "
                f"attribute (datatype property) of type {datatype}."
            )
            finding = finding.model_copy(update={"element_kind": "datatype_property", "datatype": datatype, "range": None})
        kind = finding.element_kind
        matches = self.index.match([finding.label, finding.term], kind)
        exact = next((m for m in matches if m.match_type in {"exact", "alias"}), None)
        action = finding.action

        target: AnyElement | None = None
        if finding.target_id:
            referenced = self.index.get(finding.target_id)
            if referenced is not None and element_kind(referenced) == kind:
                target = referenced
            elif referenced is not None:
                notes.append(f"The model referenced '{finding.target_id}', which is not a {_NOUNS[kind]}; ignored.")
            else:
                notes.append(f"The model referenced unknown id '{finding.target_id}'; resolved by name instead.")
        if target is None and action != "add" and exact:
            target = self.index.get(exact.element_id)
            notes.append(f"Target resolved by name to '{exact.label}'.")
        if target is None and action in {"reuse", "alias"}:
            notes.append(f"No existing {_NOUNS[kind]} matches '{finding.label}'; treated as a new {_NOUNS[kind]}.")
            action = "add"
        if target is None and action in {"modify", "conflict"}:
            self.result.discarded.append(
                Discard(finding.term, finding.action, kind, "References an element that does not exist in the baseline.")
            )
            return

        base = {
            "finding": finding,
            "original": original,
            "evidence": evidence,
            "notes": notes,
            "matches": [m.as_dict() for m in matches],
        }
        if action == "add":
            self._add(exact, **base)
        elif action == "reuse":
            self._reuse_or_alias(target, finding.term, **base)  # type: ignore[arg-type]
        elif action == "alias":
            self._alias(target, finding.alias or finding.term, **base)  # type: ignore[arg-type]
        else:
            self._modify(target, action, **base)  # type: ignore[arg-type]

    def _emit(
        self,
        *,
        finding: LLMFinding,
        original: LLMFinding,
        evidence: list[GroundedEvidence],
        notes: list[str],
        matches: list[dict[str, Any]],
        proposal_type: str,
        title: str,
        target_id: str | None = None,
        new_element: dict[str, Any] | None = None,
        changes: dict[str, dict[str, Any]] | None = None,
        depends_on: list[str] | None = None,
    ) -> ProposalDraft:
        draft = ProposalDraft(
            key=f"p{len(self.result.proposals) + 1}",
            proposal_type=proposal_type,
            element_kind=finding.element_kind,
            term=finding.term,
            title=title,
            rationale=finding.rationale.strip(),
            confidence=finding.confidence,
            target_element_id=target_id,
            new_element=new_element,
            changes=changes or {},
            alignment={"llm_action": original.action, "matches": matches, "notes": notes},
            depends_on=depends_on or [],
            evidence=evidence,
            llm_output=original.model_dump(mode="json"),
        )
        self.result.proposals.append(draft)
        return draft

    def _add(self, exact: Match | None, **base: Any) -> None:
        finding: LLMFinding = base["finding"]
        notes: list[str] = base["notes"]
        kind = finding.element_kind

        if exact is not None:
            existing = self.index.get(exact.element_id)
            assert existing is not None
            if kind != "class":
                conflict = self._property_signature_conflict(existing, finding, notes)
                if conflict:
                    self._emit(
                        **base,
                        proposal_type="conflict",
                        title=make_title("conflict", kind, existing.label),
                        target_id=existing.id,
                    )
                    return
            notes.append(
                f"Duplicate prevented: '{finding.label}' matches existing {_NOUNS[kind]} "
                f"'{existing.label}' ({exact.match_type} match)."
            )
            self._reuse_or_alias(existing, finding.term, **base)
            return

        for match in base["matches"]:
            if match["score"] >= SIMILAR_THRESHOLD:
                notes.append(
                    f"Possible duplicate of {_NOUNS[kind]} '{match['label']}' (similarity {match['score']:.2f}); "
                    "consider converting to an alias or reuse."
                )
        other_kind = self.index.exact([finding.label], None)
        if other_kind and other_kind.element_kind != kind:
            notes.append(f"The name is also used by {_NOUNS[other_kind.element_kind]} '{other_kind.label}'.")

        if kind == "class":
            earlier = self.added_classes.get(normalize_term(finding.label))
            if earlier is not None:
                known = {e.quote for e in earlier.evidence}
                earlier.evidence += [e for e in base["evidence"] if e.quote not in known]
                earlier.confidence = max(earlier.confidence, finding.confidence)
                earlier.alignment["notes"].append(f"Merged with another finding for '{finding.term}'.")
                return

        depends_on: list[str] = []
        element: dict[str, Any] = {
            "id": new_element_id(_ID_PREFIX[kind]),
            "label": finding.label,
            "description": finding.definition.strip(),
            "aliases": [finding.term] if normalize_term(finding.term) != normalize_term(finding.label) else [],
        }
        if kind == "class":
            element["local_name"] = self.unique_local_name(to_class_local_name(finding.label))
            parent_id, dependency = self.resolve_class(finding.parent, notes, "parent")
            element["parent_ids"] = [parent_id] if parent_id else []
            depends_on += [dependency] if dependency else []
        else:
            element["local_name"] = self.unique_local_name(to_property_local_name(finding.label))
            domain_id, dependency = self.resolve_class(finding.domain, notes, "domain")
            element["domain_id"] = domain_id
            depends_on += [dependency] if dependency else []
            if kind == "object_property":
                range_id, dependency = self.resolve_class(finding.range, notes, "range")
                element["range_id"] = range_id
                depends_on += [dependency] if dependency else []
            else:
                element["datatype"] = finding.datatype or "string"
                element["required"] = False
                element["multi_valued"] = False

        draft = self._emit(
            **base,
            proposal_type="add",
            title=make_title("add", kind, finding.label),
            new_element=element,
            depends_on=depends_on,
        )
        if kind == "class":
            for name in {normalize_term(finding.label), normalize_term(finding.term)}:
                self.added_classes.setdefault(name, draft)

    def _property_signature_conflict(self, existing: AnyElement, finding: LLMFinding, notes: list[str]) -> bool:
        scratch: list[str] = []
        domain_id, _ = self.resolve_class(finding.domain, scratch, "domain")
        mismatches = []
        if domain_id and getattr(existing, "domain_id", None) and domain_id != existing.domain_id:  # type: ignore[union-attr]
            mismatches.append("domain")
        if isinstance(existing, ObjectPropertyDefinition):
            range_id, _ = self.resolve_class(finding.range, scratch, "range")
            if range_id and existing.range_id and range_id != existing.range_id:
                mismatches.append("range")
        if not mismatches:
            return False
        labels = {c.id: c.label for c in self.index.elements.values() if isinstance(c, ClassDefinition)}
        current = f"{labels.get(existing.domain_id or '', '?')}"  # type: ignore[union-attr]
        if isinstance(existing, ObjectPropertyDefinition):
            current += f" → {labels.get(existing.range_id or '', '?')}"
        notes.append(
            f"Semantic conflict: existing {_NOUNS[element_kind(existing)]} '{existing.label}' is defined as "
            f"{current}, but the source uses it with a different {' and '.join(mismatches)} "
            f"({finding.domain or '?'}{' → ' + (finding.range or '?') if isinstance(existing, ObjectPropertyDefinition) else ''})."
        )
        return True

    def _reuse_or_alias(self, target: AnyElement, term: str, **base: Any) -> None:
        names = {n for n, _ in self.index.names(target)}
        if normalize_term(term) and normalize_term(term) not in names:
            base["notes"].append(f"The source term '{term}' is not yet a name of '{target.label}'; proposed as an alias.")
            self._alias(target, term, **base)
            return
        self._emit(
            **base,
            proposal_type="reuse",
            title=make_title("reuse", element_kind(target), target.label),
            target_id=target.id,
        )

    def _alias(self, target: AnyElement, alias: str, **base: Any) -> None:
        alias = alias.strip()
        kind = element_kind(target)
        names = {n for n, _ in self.index.names(target)}
        if not alias or normalize_term(alias) in names:
            base["notes"].append(f"'{alias}' is already a name of '{target.label}'.")
            self._emit(**base, proposal_type="reuse", title=make_title("reuse", kind, target.label), target_id=target.id)
            return
        clash = self.index.exact([alias], None)
        if clash and clash.element_id != target.id:
            base["notes"].append(
                f"Alias '{alias}' is already the name of {_NOUNS[clash.element_kind]} '{clash.label}'; "
                "using it for another element would make the term ambiguous."
            )
            self._emit(**base, proposal_type="conflict", title=make_title("conflict", kind, target.label), target_id=target.id)
            return
        self._emit(
            **base,
            proposal_type="alias",
            title=make_title("alias", kind, target.label, alias),
            target_id=target.id,
            changes={"aliases": {"before": list(target.aliases), "after": [*target.aliases, alias]}},
        )

    def _modify(self, target: AnyElement, action: str, **base: Any) -> None:
        finding: LLMFinding = base["finding"]
        notes: list[str] = base["notes"]
        kind = element_kind(target)
        changes: dict[str, dict[str, Any]] = {}
        definition = finding.definition.strip()
        if definition and definition != target.description:
            changes["description"] = {"before": target.description, "after": definition}
        if normalize_term(finding.label) and normalize_term(finding.label) != normalize_term(target.label):
            changes["label"] = {"before": target.label, "after": finding.label}
        if isinstance(target, ClassDefinition) and finding.parent:
            parent_id, _ = self.resolve_class(finding.parent, notes, "parent")
            if parent_id and parent_id not in target.parent_ids and parent_id != target.id:
                changes["parent_ids"] = {"before": list(target.parent_ids), "after": [*target.parent_ids, parent_id]}
        if isinstance(target, (ObjectPropertyDefinition, DatatypePropertyDefinition)) and finding.domain:
            domain_id, _ = self.resolve_class(finding.domain, notes, "domain")
            if domain_id and domain_id != target.domain_id:
                changes["domain_id"] = {"before": target.domain_id, "after": domain_id}
        if isinstance(target, ObjectPropertyDefinition) and finding.range:
            range_id, _ = self.resolve_class(finding.range, notes, "range")
            if range_id and range_id != target.range_id:
                changes["range_id"] = {"before": target.range_id, "after": range_id}
        if isinstance(target, DatatypePropertyDefinition) and finding.datatype and finding.datatype != target.datatype.value:
            changes["datatype"] = {"before": target.datatype.value, "after": finding.datatype}
        if {"domain_id", "range_id", "datatype"} & changes.keys():
            notes.append("Changes the element's signature; this is a breaking change for consumers.")

        if action == "modify" and not changes:
            notes.append("The suggested modification does not change the element; recorded as reuse.")
            self._emit(**base, proposal_type="reuse", title=make_title("reuse", kind, target.label), target_id=target.id)
            return
        self._emit(
            **base,
            proposal_type=action,
            title=make_title(action, kind, target.label),
            target_id=target.id,
            changes=changes,
        )


def _dedupe_key(draft: ProposalDraft) -> tuple[Any, ...]:
    alias = draft.changes.get("aliases", {}).get("after", [])
    label = draft.new_element["label"] if draft.new_element else ""
    return (
        draft.proposal_type,
        draft.element_kind,
        draft.target_element_id or normalize_term(label),
        normalize_term(alias[-1]) if alias else "",
    )


def align_findings(
    schema: OntologySchema, findings: list[tuple[LLMFinding, list[GroundedEvidence]]]
) -> AlignmentResult:
    aligner = _Aligner(schema)
    kind_order = {"class": 0, "object_property": 1, "datatype_property": 2}
    for finding, evidence in sorted(findings, key=lambda item: kind_order[item[0].element_kind]):
        aligner.align(finding, evidence)

    merged: dict[tuple[Any, ...], ProposalDraft] = {}
    renamed: dict[str, str] = {}
    for draft in aligner.result.proposals:
        key = _dedupe_key(draft)
        if key not in merged:
            merged[key] = draft
            continue
        keeper = merged[key]
        renamed[draft.key] = keeper.key
        known = {e.quote for e in keeper.evidence}
        keeper.evidence += [e for e in draft.evidence if e.quote not in known]
        keeper.confidence = max(keeper.confidence, draft.confidence)
        keeper.alignment["notes"] = list(dict.fromkeys(keeper.alignment["notes"] + draft.alignment["notes"]))
        keeper.alignment["notes"].append(f"Merged with a duplicate finding for '{draft.term}'.")
    for draft in merged.values():
        draft.depends_on = list(dict.fromkeys(renamed.get(k, k) for k in draft.depends_on if renamed.get(k, k) != draft.key))
    return AlignmentResult(proposals=list(merged.values()), discarded=aligner.result.discarded)
