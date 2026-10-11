from app.modules.discovery.grounding import ChunkRef, ground_quote, locate_quote

TEXT = "The \u201chaulier\u201d   (our carrier)\nis responsible for the shipment until it is delivered."


def _chunk(text: str, label: str = "C1", offset: int = 100) -> ChunkRef:
    return ChunkRef(id=f"id-{label}", label=label, document_id="doc", document_name="doc.txt", page=2, start_offset=offset, text=text)


def test_exact_quote_is_located_ignoring_case_whitespace_and_smart_quotes() -> None:
    span = locate_quote('the "haulier" (our carrier) is responsible', TEXT)
    assert span is not None
    assert TEXT[span[0] : span[1]].startswith("The \u201chaulier\u201d")
    assert TEXT[span[0] : span[1]].endswith("responsible")


def test_fuzzy_match_tolerates_small_differences_in_long_quotes() -> None:
    assert locate_quote("is responsible for the shipment until it is delivered!", TEXT) is not None


def test_unrelated_or_short_quotes_are_not_located() -> None:
    assert locate_quote("customs brokers clear all imported goods", TEXT) is None
    assert locate_quote("a", TEXT) is None


def test_ellipsis_quotes_use_the_longest_segment() -> None:
    assert locate_quote("The haulier ... is responsible for the shipment", TEXT) is not None


def test_grounding_returns_exact_source_span_with_offsets_and_context() -> None:
    chunk = _chunk(TEXT)
    evidence = ground_quote("RESPONSIBLE FOR THE SHIPMENT", "c1", {"C1": chunk}, [chunk])
    assert evidence.verified
    assert evidence.quote == "responsible for the shipment"
    assert evidence.start_offset == 100 + TEXT.index("responsible")
    assert evidence.chunk is chunk and evidence.context


def test_grounding_falls_back_to_other_chunks() -> None:
    first, second = _chunk("Nothing relevant here.", "C1"), _chunk(TEXT, "C2", 500)
    evidence = ground_quote("responsible for the shipment", "C1", {"C1": first, "C2": second}, [first, second])
    assert evidence.verified and evidence.chunk is second


def test_fabricated_quotes_are_not_verified() -> None:
    chunk = _chunk(TEXT)
    evidence = ground_quote("Customs brokers clear all imported goods.", "C1", {"C1": chunk}, [chunk])
    assert not evidence.verified and evidence.start_offset is None
