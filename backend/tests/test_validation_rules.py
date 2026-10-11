"""Unit tests for the pure structural validation rules."""

from typing import Any

import pytest

from app.modules.ontology.domain import OntologySchema
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity


def _cls(cid: str, label: str | None = None, **extra: Any) -> dict[str, Any]:
    label = label or cid.title()
    return {"id": cid, "local_name": label.replace(" ", ""), "label": label, "description": "d", **extra}


def _schema(**overrides: Any) -> OntologySchema:
    base: dict[str, Any] = {
        "namespace": "https://example.com/onto#",
        "prefix": "ex",
        "classes": [_cls("a", "Alpha"), _cls("b", "Beta")],
        "object_properties": [
            {"id": "r", "local_name": "relates", "label": "relates", "description": "d",
             "domain_id": "a", "range_id": "b"}
        ],
        "datatype_properties": [
            {"id": "p", "local_name": "code", "label": "code", "description": "d", "domain_id": "a"}
        ],
    }
    base.update(overrides)
    return OntologySchema.model_validate(base)


def _codes(schema: OntologySchema, severity: Severity | None = None) -> set[str]:
    return {i.code for i in validate_schema(schema) if severity is None or i.severity == severity}


def test_clean_schema_has_no_issues() -> None:
    assert validate_schema(_schema()) == []


@pytest.mark.parametrize(
    ("namespace", "code"),
    [
        ("not a namespace", "NAMESPACE_INVALID"),
        ("https:///missing-host#", "NAMESPACE_INVALID"),
        ("https://example.com/onto", "NAMESPACE_MISSING_SEPARATOR"),
    ],
)
def test_namespace_rules(namespace: str, code: str) -> None:
    assert code in _codes(_schema(namespace=namespace), Severity.ERROR)


def test_urn_namespace_is_accepted() -> None:
    assert _codes(_schema(namespace="urn:example:onto:")) == set()
    assert _codes(_schema(namespace="urn:example:onto/")) == set()
    assert "NAMESPACE_MISSING_SEPARATOR" in _codes(_schema(namespace="https://example.com/a:"))


@pytest.mark.parametrize(("prefix", "code"), [("1x", "PREFIX_INVALID"), ("owl", "PREFIX_RESERVED")])
def test_prefix_rules(prefix: str, code: str) -> None:
    assert code in _codes(_schema(prefix=prefix), Severity.ERROR)


def test_empty_ontology_warning() -> None:
    schema = _schema(classes=[], object_properties=[], datatype_properties=[])
    assert _codes(schema) == {"ONTOLOGY_EMPTY"}


def test_duplicates_and_invalid_local_names() -> None:
    schema = _schema(
        classes=[
            _cls("a", "Alpha"),
            {**_cls("b", "Beta"), "local_name": "Alpha"},
            {**_cls("c", "Gamma"), "local_name": "alpha"},
            {**_cls("d", "Delta"), "local_name": "Has Space"},
        ]
    )
    issues = validate_schema(schema)
    dup = [i for i in issues if i.code == "DUPLICATE_LOCAL_NAME"]
    assert {i.element_id for i in dup} == {"a", "b"}
    assert all(i.severity == Severity.ERROR for i in dup)
    assert any(i.code == "LOCAL_NAME_CASE_COLLISION" and i.element_id == "c" for i in issues)
    assert any(i.code == "LOCAL_NAME_INVALID" and i.element_id == "d" for i in issues)


def test_duplicate_element_ids_are_detected() -> None:
    schema = _schema(classes=[_cls("a", "Alpha"), _cls("a", "Other")])
    assert "DUPLICATE_ELEMENT_ID" in _codes(schema, Severity.ERROR)


def test_hierarchy_rules() -> None:
    schema = _schema(
        classes=[
            _cls("a", "Alpha", parent_ids=["c"]),
            _cls("b", "Beta", parent_ids=["a"]),
            _cls("c", "Gamma", parent_ids=["b"]),
            _cls("d", "Delta", parent_ids=["d"]),
            _cls("e", "Epsilon", parent_ids=["missing"]),
        ]
    )
    issues = validate_schema(schema)
    cycles = [i for i in issues if i.code == "CLASS_HIERARCHY_CYCLE"]
    assert len(cycles) == 1, "a cycle is reported once"
    assert "→" in cycles[0].message
    assert set([cycles[0].element_id, *cycles[0].related_element_ids]) == {"a", "b", "c"}
    assert any(i.code == "CLASS_PARENT_SELF" and i.element_id == "d" for i in issues)
    assert any(i.code == "CLASS_PARENT_UNKNOWN" and i.element_id == "e" for i in issues)


def test_object_property_domain_and_range_rules() -> None:
    schema = _schema(
        object_properties=[
            {"id": "r1", "local_name": "r1", "label": "r1", "description": "d", "domain_id": None, "range_id": "b"},
            {"id": "r2", "local_name": "r2", "label": "r2", "description": "d", "domain_id": "a", "range_id": None},
            {"id": "r3", "local_name": "r3", "label": "r3", "description": "d", "domain_id": "zz", "range_id": "b"},
            {"id": "r4", "local_name": "r4", "label": "r4", "description": "d", "domain_id": "a", "range_id": "zz"},
        ]
    )
    by_element = {(i.element_id, i.code) for i in validate_schema(schema)}
    assert ("r1", "PROPERTY_DOMAIN_MISSING") in by_element
    assert ("r2", "PROPERTY_RANGE_MISSING") in by_element
    assert ("r3", "PROPERTY_DOMAIN_UNKNOWN") in by_element
    assert ("r4", "PROPERTY_RANGE_UNKNOWN") in by_element


def test_datatype_property_domain_rules() -> None:
    schema = _schema(
        datatype_properties=[
            {"id": "p1", "local_name": "p1", "label": "p1", "description": "d", "domain_id": "zz"},
        ]
    )
    assert "PROPERTY_DOMAIN_UNKNOWN" in _codes(schema, Severity.ERROR)


def test_duplicate_relationship_and_attribute_warnings() -> None:
    schema = _schema(
        object_properties=[
            {"id": "r1", "local_name": "relates", "label": "relates", "description": "d", "domain_id": "a", "range_id": "b"},
            {"id": "r2", "local_name": "relatesTo", "label": "Relates", "description": "d", "domain_id": "a", "range_id": "b"},
        ],
        datatype_properties=[
            {"id": "p1", "local_name": "code", "label": "code", "description": "d", "domain_id": "a"},
            {"id": "p2", "local_name": "codeValue", "label": "Code", "description": "d", "domain_id": "a"},
        ],
    )
    warnings = _codes(schema, Severity.WARNING)
    assert {"DUPLICATE_RELATIONSHIP", "DUPLICATE_ATTRIBUTE"} <= warnings


def test_label_alias_and_description_rules() -> None:
    schema = _schema(
        classes=[
            _cls("a", "Alpha", aliases=["Vendor"]),
            {**_cls("b", "Beta"), "aliases": ["vendor"], "description": ""},
            {**_cls("c", "alpha"), "local_name": "AlphaTwo"},
        ]
    )
    issues = validate_schema(schema)
    codes = {(i.element_id, i.code) for i in issues}
    assert ("a", "ALIAS_CONFLICT") in codes and ("b", "ALIAS_CONFLICT") in codes
    assert ("a", "DUPLICATE_CLASS_LABEL") in codes and ("c", "DUPLICATE_CLASS_LABEL") in codes
    assert ("b", "DESCRIPTION_MISSING") in codes


def test_info_level_hints() -> None:
    schema = _schema(
        classes=[
            _cls("a", "Alpha"),
            _cls("b", "Beta", parent_ids=["a"]),
            {**_cls("c", "Gamma"), "local_name": "gamma"},
        ],
        datatype_properties=[
            {"id": "p1", "local_name": "code", "label": "code", "description": "d", "domain_id": "a"},
            {"id": "p2", "local_name": "betaCode", "label": "code", "description": "d", "domain_id": "b"},
        ],
    )
    info = {(i.element_id, i.code) for i in validate_schema(schema) if i.severity == Severity.INFO}
    assert ("c", "ORPHAN_CLASS") in info
    assert ("c", "LOCAL_NAME_CONVENTION") in info
    assert ("p2", "INHERITED_ATTRIBUTE_REDECLARED") in info


def test_issues_are_sorted_by_severity() -> None:
    schema = _schema(
        prefix="owl",
        classes=[_cls("a", "Alpha"), {**_cls("b", "Beta"), "description": ""}, _cls("c", "Gamma")],
    )
    ranks = {"error": 0, "warning": 1, "info": 2}
    severities = [ranks[i.severity.value] for i in validate_schema(schema)]
    assert severities == sorted(severities)
