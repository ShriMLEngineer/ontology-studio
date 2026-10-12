"""Value normalisation between extraction and candidate-fact validation.

Unit tests of the pure normaliser (percentages, decimals, integers, booleans, dates, ambiguity, invalid
numerics, ontology-derived value specs) and API-level regressions on a Meridian-style supplier scorecard:
the same raw values arrive from a structured source and from an LLM-extracted PDF, are typed by the same
logic, and still face strict structural and SHACL validation. Historical builds are never rewritten.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from rdflib import Literal
from rdflib.namespace import XSD
from sqlalchemy import create_engine, text

from app.db.migrations import alembic_config, upgrade_database
from app.main import create_app
from app.modules.graph.projection import project_rdf
from app.modules.kg.deployments import load_projection
from app.modules.kg.models import KgBuild
from app.modules.kg.normalization import (
    AMBIGUOUS,
    EXACT,
    FAILED,
    NORMALIZED,
    ValueSpec,
    normalize_value,
    parse_literal,
    same_value,
    value_spec_for,
)
from app.modules.ontology.domain import DatatypePropertyDefinition, XsdDatatype
from tests.conftest import make_settings
from tests.fakes import ScriptedLLMProvider
from tests.kg_helpers import SME, facts, publish, run_build, upload
from tests.pdf_fixture import make_pdf

PERCENT = ValueSpec("decimal", "on-time delivery percentage", unit="percent", scale="0-100")
PLAIN = ValueSpec("decimal", "defect rate")
INTEGER_PERCENT = ValueSpec("integer", "score %", unit="percent", scale="0-100")
INTEGER = ValueSpec("integer", "tier")
BOOLEAN = ValueSpec("boolean", "preferred")
DATE = ValueSpec("date", "order date")


def _outcome(raw: str, spec: ValueSpec) -> tuple[str, str | None, str]:
    result = normalize_value(raw, spec)
    return result.status, result.normalized_value, result.rule


# ---------------------------------------------------------------------------------- percentages


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("97.0%", "97.0"),
        ("94.5%", "94.5"),
        ("88.0%", "88.0"),
        ("98.2 percentg", "98.2"),  # a one-edit misspelling of "percent"
        ("97 percent", "97"),
        ("97.0 %", "97.0"),
        ("97.0 pct", "97.0"),
        ("97.0 per cent", "97.0"),
        ("97.0 percentage", "97.0"),
        ("97.0%.", "97.0"),
        ("  97.0%  ", "97.0"),
        ("-2.5%", "-2.5"),
        ("100%", "100"),
    ],
)
def test_percentages_of_percentage_attributes_are_stored_on_the_0_100_scale(raw: str, expected: str) -> None:
    result = normalize_value(raw, PERCENT)
    assert (result.status, result.normalized_value) == (NORMALIZED, expected)
    assert (result.rule, result.unit, result.scale) == ("percentage-0-100", "percent", "0-100")
    assert result.raw_value == raw, "the original value is preserved exactly"
    assert result.datatype == "decimal" and result.datatype_iri == "http://www.w3.org/2001/XMLSchema#decimal"
    assert result.as_dict()["normalized_value"] == expected


def test_values_without_a_unit_are_never_rescaled() -> None:
    assert _outcome("97.0", PERCENT) == (EXACT, "97.0", "as-written")
    assert _outcome("0.97", PERCENT) == (EXACT, "0.97", "as-written"), "a fraction is not multiplied or divided"
    assert _outcome("120%", PERCENT)[:2] == (NORMALIZED, "120"), "range limits belong to SHACL shapes, not to the normaliser"


def test_percent_units_are_not_stripped_from_attributes_that_are_not_percentages() -> None:
    result = normalize_value("97.0%", PLAIN)
    assert (result.status, result.normalized_value, result.rule) == (AMBIGUOUS, None, "percent-not-defined")
    assert "not defined as a percentage" in result.message
    assert normalize_value("97.0%", ValueSpec("string", "note")).status == EXACT, "strings keep their symbols"
    conflicting = ValueSpec("decimal", "share", unit="percent", note="its definition states a 0-1 (fractional) scale")
    assert _outcome("97%", conflicting) == (AMBIGUOUS, None, "percent-scale-conflict")


@pytest.mark.parametrize("raw", ["5 kg", "$12.50", "12.50 USD", "97.0 on-time", "3 \u2030", "98.2 perfect", "98.2 percept"])
def test_unrecognised_or_undefined_units_are_held_not_converted(raw: str) -> None:
    for spec in (PLAIN, PERCENT):
        result = normalize_value(raw, spec)
        assert (result.status, result.normalized_value) == (AMBIGUOUS, None), raw
        assert "not convert" in result.message or "neither converted" in result.message


@pytest.mark.parametrize("raw", ["12,5", "97,5%", "0,234", "1,2345"])
def test_comma_decimals_are_ambiguous(raw: str) -> None:
    assert normalize_value(raw, PERCENT).status == AMBIGUOUS
    assert normalize_value(raw, PERCENT).rule == "decimal-comma"


# ---------------------------------------------------------------------------------- invalid numerics


@pytest.mark.parametrize(
    "raw",
    ["ninety", "n/a", "approx. 1000", "~97%", "1.2.3", "--5", "97.0% on time", "NaN", "1,2,3", "10-20%", "%97", "97%%"],
)
def test_invalid_numerics_fail_with_the_original_datatype_message(raw: str) -> None:
    result = normalize_value(raw, PERCENT)
    assert (result.status, result.normalized_value) == (FAILED, None)
    assert result.message == parse_literal(raw, "decimal")[2], "reviewers keep seeing the same reason"


def test_empty_values_fail() -> None:
    assert _outcome("   ", PERCENT)[:2] == (FAILED, None)
    assert normalize_value(None, PERCENT).status == FAILED


# ---------------------------------------------------------------------------------- integers, decimals, booleans, dates


def test_decimals_and_integers() -> None:
    assert _outcome("1,250.50", PLAIN) == (NORMALIZED, "1250.50", "thousands-separator")
    assert _outcome("007", INTEGER) == (NORMALIZED, "7", "canonical-form")
    assert _outcome("42.0", INTEGER) == (NORMALIZED, "42", "integral-decimal")
    assert _outcome("1,234", INTEGER) == (NORMALIZED, "1234", "thousands-separator")
    assert normalize_value("42.5", INTEGER).status == FAILED, "values are never rounded"
    assert normalize_value("42.5", INTEGER).message == "'42.5' is not an integer."
    assert _outcome("97.0%", INTEGER_PERCENT)[:2] == (NORMALIZED, "97")
    assert normalize_value("97.5%", INTEGER_PERCENT).status == FAILED
    assert _outcome("9999999999", ValueSpec("int", "n"))[0] == FAILED
    assert _outcome("1.5e3", ValueSpec("double", "x")) == (NORMALIZED, "1500.0", "canonical-form")


@pytest.mark.parametrize(("raw", "expected"), [("Yes.", "true"), ('"no"', "false"), ("TRUE", "true"), (" 1 ", "true")])
def test_booleans(raw: str, expected: str) -> None:
    assert normalize_value(raw, BOOLEAN).normalized_value == expected
    assert normalize_value("maybe", BOOLEAN).status == FAILED


@pytest.mark.parametrize(
    ("raw", "status", "expected"),
    [
        ("2026-07-14", EXACT, "2026-07-14"),
        ("2026/07/14", NORMALIZED, "2026-07-14"),
        ("2026.7.4", NORMALIZED, "2026-07-04"),
        ("2026-07-14T00:00:00", NORMALIZED, "2026-07-14"),
        ("25/07/2026", NORMALIZED, "2026-07-25"),
        ("07/25/2026", NORMALIZED, "2026-07-25"),
        ("05/05/2026", NORMALIZED, "2026-05-05"),
        ("14/07/2026", NORMALIZED, "2026-07-14"),
        ("04/07/2026", AMBIGUOUS, None),  # day/month or month/day
        ("2026-07-14T10:30:00", FAILED, None),  # a time of day is never dropped
        ("31/02/2026", FAILED, None),
        ("13/14/2026", FAILED, None),
    ],
)
def test_iso_dates_are_normalised_only_when_the_reading_is_unique(raw: str, status: str, expected: str | None) -> None:
    result = normalize_value(raw, DATE)
    assert (result.status, result.normalized_value) == (status, expected)


def test_values_that_were_valid_keep_their_canonical_form() -> None:
    """Deterministic structured values are not touched: the strict parser's output is the exact fallback."""
    for raw, datatype in (("420.00", "decimal"), ("12.50", "decimal"), ("8400.00", "decimal"), ("2", "integer"),
                          ("2026-07-14", "date"), ("low", "string"), ("true", "boolean")):
        valid, canonical, _ = parse_literal(raw, datatype)
        result = normalize_value(raw, ValueSpec(datatype, "x"))
        assert valid and result.status == EXACT and result.normalized_value == canonical == raw


def test_grouped_thousands_never_start_with_a_zero_group() -> None:
    """'0,234' used to be read as 234 (silent corruption); it is now unreadable and therefore ambiguous."""
    assert parse_literal("0,234", "decimal")[0] is False
    assert parse_literal("1,234", "decimal") == (True, "1234", "")
    assert parse_literal("1,250.50", "float")[1] == "1250.5"


def test_numeric_values_compare_by_value() -> None:
    assert same_value("97", "97.0", "decimal") and same_value("94.5", "94.50", "decimal")
    assert not same_value("97", "98", "decimal") and not same_value("true", "false", "boolean")
    assert same_value("high", "high", "string") and not same_value("97", "97.0", "string")


@pytest.mark.parametrize(
    ("raw", "quote", "supported"),
    [
        ("97 percent", "delivered 97.0% of orders on time", True),
        ("94.50%", "delivered 94.5% of orders", True),
        ("97 percent", "delivered 97.5% of orders on time", False),  # 97 is not the token "97" of 97.5
        ("97 percent", "delivered 97,5% of orders on time", False),  # nor of the decimal comma 97,5
        ("97 percent", "since 1997 the supplier", False),
        ("97 percent", "supplier S-97 delivered", False),
        ("97 percent", "supplier S-100 delivered 97 pct", True),
        ("1,250", "stock of 1250 units", True),
        ("1,250", "stock of 12,500 units", False),
    ],
)
def test_a_quote_supports_a_normalised_number_only_when_it_states_that_number(raw: str, quote: str, supported: bool) -> None:
    from app.modules.kg.validation import _quote_states_number

    spec = PERCENT if "%" in raw or "percent" in raw else PLAIN
    normalization = normalize_value(raw, spec)
    assert normalization.status == NORMALIZED
    assert _quote_states_number(quote, normalization) is supported


# ---------------------------------------------------------------------------------- the ontology decides


def _prop(label: str, *, local_name: str = "attr", description: str = "", datatype: str = "decimal",
          aliases: list[str] | None = None) -> DatatypePropertyDefinition:
    return DatatypePropertyDefinition(
        id="dp-x", local_name=local_name, label=label, description=description, aliases=aliases or [],
        domain_id="cls-supplier", datatype=XsdDatatype(datatype),
    )


@pytest.mark.parametrize(
    "prop",
    [
        _prop("on-time delivery percentage"),
        _prop("On-time delivery %"),
        _prop("on-time delivery", local_name="onTimeDeliveryPct"),
        _prop("on-time delivery", local_name="on_time_percent"),
        _prop("on-time delivery", aliases=["OTD percentage"]),
        _prop("on-time delivery", description="Share of lines delivered on time, expressed as a percentage."),
        _prop("on-time delivery", description="Fraction of lines delivered on time as a percentage (0-100)."),
    ],
)
def test_percentage_attributes_are_recognised_from_their_definition(prop: DatatypePropertyDefinition) -> None:
    spec = value_spec_for(prop)
    assert (spec.unit, spec.scale, spec.datatype) == ("percent", "0-100", "decimal")


@pytest.mark.parametrize(
    "prop",
    [
        _prop("capacity"),
        _prop("unit cost", description="Cost of one unit in the supplier's currency."),
        _prop("percentile rank"),
        _prop("on-time delivery rate", description="Late lines divided by all lines."),
        _prop("completion percentage", datatype="string"),
        _prop("completed", datatype="boolean", description="Percentage complete flag"),
    ],
)
def test_other_attributes_are_not_assumed_to_be_percentages(prop: DatatypePropertyDefinition) -> None:
    assert value_spec_for(prop).unit is None


def test_a_documented_fractional_scale_is_not_converted_to_the_percentage_scale() -> None:
    spec = value_spec_for(_prop("on-time delivery percentage", description="Stored as a fraction between 0 and 1."))
    assert (spec.unit, spec.scale) == ("percent", None) and spec.note
    assert normalize_value("97%", spec).rule == "percent-scale-conflict"


# ---------------------------------------------------------------------------------- scorecard (API level)

PCT_DESCRIPTION = "Share of order lines delivered on or before the promised date, expressed as a percentage (0-100)."
SCORECARD_CSV = (
    "supplier_id,legal_name,on_time,defect_rate\n"
    "S-101,Meridian Fasteners,97.0%,3.5\n"
    "S-102,Meridian Castings,94.5%,12%\n"
    "S-103,Meridian Seals,88.0%,2.0\n"
    "S-104,Meridian Valves,98.2 percentg,\n"
    'S-105,Meridian Gaskets,ninety,1.0\n'
    'S-106,Meridian Bearings,"97,5%",\n'
)
CSV = "meridian_scorecard.csv"
PDF = "meridian_scorecard.pdf"
PDF_LINES = [
    "Meridian SCM supplier scorecard.",
    "Meridian Fasteners (supplier S-101) delivered 97.0% of orders on time.",
    "Meridian Castings (supplier S-102) delivered 94.5% of orders on time.",
    "Meridian Seals (supplier S-103) delivered 88.0% of orders on time.",
    "Meridian Valves (supplier S-104) delivered 98.2 percentg of orders on time.",
    "Meridian Gaskets (supplier S-105) delivered ninety of orders on time.",
    "Meridian Bearings (supplier S-106) delivered 97,5% of orders on time.",
    "Meridian Castings (supplier S-102) reported a defect rate of 12%.",
    "Meridian Seals (supplier S-103) was restated at 89.0% on time after an audit.",
]
# supplier, expected status, expected stored value (None: the raw value stays), expected normalisation status
ON_TIME = [
    ("Meridian Fasteners", "accepted", "97.0", NORMALIZED),
    ("Meridian Castings", "accepted", "94.5", NORMALIZED),
    ("Meridian Seals", "accepted", "88.0", NORMALIZED),
    ("Meridian Valves", "accepted", "98.2", NORMALIZED),
    ("Meridian Gaskets", "rejected", None, FAILED),
    ("Meridian Bearings", "quarantined", None, AMBIGUOUS),
]


def _scorecard(client: TestClient, *, csv: bool = True, pdf: bool = False, llm: dict[str, Any] | None = None) -> dict[str, Any]:
    project = client.get("/api/projects").json()[0]
    ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
    url = f"/api/ontologies/{ontology['id']}/datatype-properties"
    percentage = client.post(url, json={"label": "on-time delivery percentage", "domain_id": "cls-supplier",
                                        "datatype": "decimal", "description": PCT_DESCRIPTION})
    rate = client.post(url, json={"label": "defect rate", "domain_id": "cls-supplier", "datatype": "decimal",
                                  "description": "Defects per thousand units shipped."})
    assert percentage.status_code == rate.status_code == 201, (percentage.text, rate.text)
    version = publish(client, ontology["id"], "1.0.0")
    env: dict[str, Any] = {
        "client": client, "project": project, "ontology": ontology, "version": version, "documents": {},
        "mappings": {}, "percentage": percentage.json(), "rate": rate.json(),
    }
    if csv:
        document = upload(client, project["id"], CSV, SCORECARD_CSV.encode())
        spec = {
            "entities": [{
                "key": "s", "class_id": "cls-supplier", "id_column": "supplier_id", "label_column": "legal_name",
                "attributes": [
                    {"column": "legal_name", "property_id": "dp-legal-name"},
                    {"column": "on_time", "property_id": env["percentage"]["id"]},
                    {"column": "defect_rate", "property_id": env["rate"]["id"]},
                ],
            }],
            "relationships": [],
        }
        mapping = client.post(
            f"/api/projects/{project['id']}/kg/mappings",
            json={"document_id": document["id"], "ontology_version_id": version["id"], "name": "scorecard",
                  "spec": spec, "updated_by": SME},
        )
        assert mapping.status_code == 201, mapping.text
        env["documents"][CSV], env["mappings"][CSV] = document, mapping.json()
    if pdf:
        env["documents"][PDF] = upload(client, project["id"], PDF, make_pdf(["\n".join(PDF_LINES)]))
        client.app.state.llm_provider = ScriptedLLMProvider([llm or _llm(env)])  # type: ignore[attr-defined]
    return env


def _line(supplier_id: str) -> str:
    return next(line for line in PDF_LINES if f"({'supplier ' + supplier_id})" in line and "defect" not in line)


def _llm(env: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Scripted extraction of the PDF; ``overrides`` replaces the raw on-time value per supplier id."""
    suppliers = [("S-101", "Meridian Fasteners", "97.0%"), ("S-102", "Meridian Castings", "94.5%"),
                 ("S-103", "Meridian Seals", "88.0%"), ("S-104", "Meridian Valves", "98.2 percentg"),
                 ("S-105", "Meridian Gaskets", "ninety"), ("S-106", "Meridian Bearings", "97,5%")]
    entities, attributes = [], []
    for index, (identifier, name, value) in enumerate(suppliers, start=1):
        quote = _line(identifier)
        entities.append({"ref": f"E{index}", "name": name, "class_id": "cls-supplier", "identifier": identifier,
                         "chunk_id": "C1", "quote": quote})
        attributes.append({"entity_ref": f"E{index}", "property_id": env["percentage"]["id"],
                           "value": (overrides or {}).get(identifier, value), "chunk_id": "C1", "quote": quote})
    defect = next(line for line in PDF_LINES if "defect rate" in line)
    attributes.append({"entity_ref": "E2", "property_id": env["rate"]["id"], "value": "12%", "chunk_id": "C1",
                       "quote": defect})
    return {"entities": entities, "relationships": [], "attributes": attributes, "unknown_concepts": []}


def _attribute(items: list[dict[str, Any]], supplier: str, label: str, origin: str | None = None) -> dict[str, Any]:
    matches = [f for f in items if f["subject_label"] == supplier and f["predicate_label"] == label
               and (origin is None or f["origin"] == origin)]
    assert matches, (supplier, label, [(f["subject_label"], f["predicate_label"], f["value"]) for f in items])
    return matches[0]


def _check_on_time_table(client: TestClient, build: dict[str, Any], origin: str) -> None:
    items = facts(client, build["id"], kind="attribute", origin=origin)
    for supplier, status, stored, normalization in ON_TIME:
        fact = _attribute(items, supplier, "on-time delivery percentage")
        assert fact["status"] == status, (supplier, fact["reasons"])
        assert fact["normalization_status"] == normalization
        detail = client.get(f"/api/kg/facts/{fact['id']}").json()
        record = detail["value_normalization"]
        assert record["status"] == normalization and record["datatype"] == "decimal"
        assert record["datatype_iri"] == "http://www.w3.org/2001/XMLSchema#decimal"
        results = detail["lanes"]["shacl"]["results"]
        if status == "accepted":
            assert (fact["value"], fact["datatype"]) == (stored, "decimal")
            assert record["normalized_value"] == stored and record["rule"] == "percentage-0-100"
            assert (record["unit"], record["scale"]) == ("percent", "0-100")
            assert [r for r in results if r["severity"] == "Violation"] == [], "SHACL conforms to the typed literal"
            assert detail["structural"]["passed"] is True and detail["evidence"]["status"] == "supported"
        elif status == "rejected":
            assert fact["value"] == record["raw_value"] == "ninety"
            assert any(r["component"] == "DatatypeConstraintComponent" and r["outcome"] == "reject" for r in results), (
                "strict SHACL still rejects a value that is not a decimal"
            )
            assert "'ninety' is not a decimal number." in fact["reasons"]
        else:
            assert fact["value"] == record["raw_value"] == "97,5%" and record["normalized_value"] is None
            assert results == [], "an ambiguous value is never asserted as data, so SHACL has nothing to judge"
            assert any("ambiguous" in reason for reason in fact["reasons"])
            assert detail["structural"]["passed"] is False


def test_meridian_structured_percentages_pass_validation_without_weakening_it(seeded_client: TestClient) -> None:
    env = _scorecard(seeded_client)
    build = run_build(env, names=[CSV])
    client = env["client"]
    _check_on_time_table(client, build, "structured")

    attributes = facts(client, build["id"], kind="attribute")
    unit_check = _attribute(attributes, "Meridian Castings", "defect rate")
    assert unit_check["status"] == "quarantined" and unit_check["normalization_status"] == AMBIGUOUS
    assert any("not defined as a percentage" in reason for reason in unit_check["reasons"]), "% is not stripped"
    untouched = _attribute(attributes, "Meridian Fasteners", "defect rate")
    assert (untouched["status"], untouched["value"], untouched["normalization_status"]) == ("accepted", "3.5", EXACT)

    detail = client.get(f"/api/kg/facts/{_attribute(attributes, 'Meridian Valves', 'on-time delivery percentage')['id']}").json()
    assert detail["sources"][0]["record"]["on_time"] == "98.2 percentg", "the source record is preserved"
    assert detail["value_normalization"]["raw_value"] == "98.2 percentg"

    graph = client.get(f"/api/kg/builds/{build['id']}/graph").json()
    node = next(n for n in graph["nodes"] if n["identifier"] == "S-104")
    assert {p["label"]: p["values"] for p in node["properties"]}["on-time delivery percentage"] == ["98.2"]
    assert not any(n["identifier"] in {"S-105", "S-106"} and any(
        p["label"] == "on-time delivery percentage" for p in n["properties"]) for n in graph["nodes"])

    stage = next(s for s in build["stages"] if s["key"] == "structural_validation")
    assert stage["counts"]["values_normalized"] >= 4 and stage["counts"]["values_ambiguous"] == 2
    assert build["stats"]["normalization"]["by_rule"]["normalized:percentage-0-100"] == 4
    logs = [line["message"] for line in client.get(f"/api/kg/builds/{build['id']}/logs").json()]
    assert any("normalised by rule 'percentage-0-100'" in m for m in logs)
    metrics = {m["key"]: m for s in client.get(f"/api/kg/builds/{build['id']}/evaluation").json()["sections"] for m in s["metrics"]}
    assert metrics["normalized_values"]["numerator"] == 4 and metrics["ambiguous_values"]["value"] == 2


def test_meridian_pdf_extraction_uses_the_same_normalisation(seeded_client: TestClient) -> None:
    env = _scorecard(seeded_client, csv=False, pdf=True)
    build = run_build(env, names=[PDF])
    client = env["client"]
    _check_on_time_table(client, build, "llm")

    items = facts(client, build["id"], kind="attribute")
    percent_on_rate = _attribute(items, "Meridian Castings", "defect rate")
    assert percent_on_rate["status"] == "quarantined" and percent_on_rate["normalization_status"] == AMBIGUOUS
    valves = _attribute(items, "Meridian Valves", "on-time delivery percentage")
    detail = client.get(f"/api/kg/facts/{valves['id']}").json()
    source = detail["sources"][0]
    assert source["located"] is True and "98.2 percentg" in source["quote"], "evidence quote and original output kept"
    assert detail["value_normalization"]["raw_value"] == "98.2 percentg"
    assert detail["evidence"]["status"] == "supported", "the quote contains the value as the source wrote it"


def test_structured_and_text_sources_agree_on_numerically_equal_values(seeded_client: TestClient) -> None:
    env = _scorecard(seeded_client, pdf=True)
    response = _llm(env, {"S-101": "97 percent", "S-102": "94.50%", "S-103": "89.0%"})
    seals = next(a for a in response["attributes"] if a["entity_ref"] == "E3" and a["property_id"] == env["percentage"]["id"])
    seals["quote"] = next(line for line in PDF_LINES if "restated at 89.0%" in line)
    seeded_client.app.state.llm_provider = ScriptedLLMProvider([response])  # type: ignore[attr-defined]
    build = run_build(env, names=[CSV, PDF])
    items = facts(env["client"], build["id"], kind="attribute")

    equal = _attribute(items, "Meridian Fasteners", "on-time delivery percentage", origin="llm")
    assert (equal["status"], equal["value"]) == ("accepted", "97"), "97 equals 97.0: not a conflict"
    equal = _attribute(items, "Meridian Castings", "on-time delivery percentage", origin="llm")
    assert (equal["status"], equal["value"]) == ("accepted", "94.50"), "the quote states 94.5%, the same number"
    conflicting = _attribute(items, "Meridian Seals", "on-time delivery percentage", origin="llm")
    assert conflicting["status"] == "quarantined" and conflicting["value"] == "89.0"
    assert any("Conflicts with '88.0'" in reason for reason in conflicting["reasons"])


def test_a_value_the_quote_does_not_state_is_not_supported_by_normalisation(seeded_client: TestClient) -> None:
    """The LLM wrote '97 percent' but the source says 97,5%: normalising must never turn that into 'supported'."""
    env = _scorecard(seeded_client, csv=False, pdf=True)
    seeded_client.app.state.llm_provider = ScriptedLLMProvider([_llm(env, {"S-106": "97 percent"})])  # type: ignore[attr-defined]
    build = run_build(env, names=[PDF])
    fact = _attribute(facts(env["client"], build["id"], kind="attribute"), "Meridian Bearings", "on-time delivery percentage")
    assert fact["normalization_status"] == NORMALIZED and fact["value"] == "97", "the value itself is convertible"
    assert (fact["status"], fact["evidence_status"]) == ("quarantined", "weak")
    assert any("does not mention the value '97 percent'" in reason for reason in fact["reasons"])


def test_normalised_values_are_typed_rdf_literals_after_deployment(seeded_client: TestClient) -> None:
    env = _scorecard(seeded_client)
    build = run_build(env, names=[CSV], graph_connection_id="oxigraph-embedded")
    client = env["client"]
    local_name = env["percentage"]["local_name"]

    session_factory = seeded_client.app.state.session_factory  # type: ignore[attr-defined]
    with session_factory() as session:
        row = session.get(KgBuild, build["id"])
        assert row is not None
        snapshot, projection = load_projection(session, row)
    rdf = project_rdf(projection, snapshot, build["stats"]["shacl"]["data_namespace"], build["id"])
    literals = {str(o): o for _, p, o in rdf.data if str(p).endswith(local_name)}
    assert set(literals) == {"97.0", "94.5", "88.0", "98.2"}, "the lexical form is exactly what was normalised"
    assert all(isinstance(o, Literal) and o.datatype == XSD.decimal for o in literals.values())

    deployment = next(d for d in client.get(f"/api/kg/builds/{build['id']}/deployments").json() if d["target_kind"] == "oxigraph")
    query = f'SELECT ?o WHERE {{ ?s ?p ?o FILTER(STRENDS(STR(?p), "{local_name}")) }}'
    response = client.post(f"/api/kg/deployments/{deployment['id']}/query", json={"query": query})
    assert response.status_code == 200, response.text
    stored = response.json()["rows"]
    # The store may canonicalise the lexical form of a decimal (97.0 -> 97); the value and datatype are what matter.
    assert sorted(Decimal(row["o"]["value"]) for row in stored) == [Decimal(88), Decimal("94.5"), Decimal(97), Decimal("98.2")]
    assert {(row["o"]["type"], row["o"]["datatype"]) for row in stored} == {("literal", str(XSD.decimal))}


def _fact_rows(db_path: Path, build_id: str) -> list[tuple[Any, ...]]:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = [c for c in (row[1] for row in connection.execute(text("PRAGMA table_info(kg_candidate_facts)")))
                       if c != "value_normalization"]
            query = text(f"SELECT {', '.join(columns)} FROM kg_candidate_facts WHERE build_id = :id ORDER BY sequence")
            return [tuple(row) for row in connection.execute(query, {"id": build_id})]
    finally:
        engine.dispose()


def test_historical_builds_are_never_mutated_by_new_builds_or_the_migration(db_path: Path) -> None:
    settings = make_settings(db_path, seed=True)
    with TestClient(create_app(settings)) as client:
        env = _scorecard(client)
        first = run_build(env, names=[CSV])
        recorded = _fact_rows(db_path, first["id"])
        assert recorded
        second = run_build(env, names=[CSV])  # a new build uses the corrected logic
        assert _fact_rows(db_path, first["id"]) == recorded, "building again never rewrites an earlier build"
        assert second["id"] != first["id"]
        evaluation = client.get(f"/api/kg/builds/{second['id']}/evaluation").json()
        assert "normalized_values" in {m["key"] for s in evaluation["sections"] for m in s["metrics"]}
        attribute = _attribute(facts(client, first["id"], kind="attribute"), "Meridian Valves", "on-time delivery percentage")
        first_evaluation = client.get(f"/api/kg/builds/{first['id']}/evaluation").json()

    # Builds created before value normalisation have no audit record: the column is added empty (NULL).
    command.downgrade(alembic_config(settings.database_url), "0010")
    upgrade_database(settings.database_url)
    assert _fact_rows(db_path, first["id"]) == recorded, "the migration changes no historical row"
    with TestClient(create_app(settings)) as client:
        reloaded = client.get(f"/api/kg/facts/{attribute['id']}").json()
        assert reloaded["value_normalization"] is None and reloaded["normalization_status"] is None
        assert (reloaded["status"], reloaded["value"]) == (attribute["status"], attribute["value"])
        assert client.get(f"/api/kg/builds/{first['id']}/evaluation").json() == first_evaluation, (
            "a stored evaluation is a snapshot of the build and is never recomputed"
        )
