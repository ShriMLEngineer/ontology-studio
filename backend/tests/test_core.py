from app.core.ids import new_element_id, utcnow


def test_utcnow_is_strictly_increasing_and_timezone_aware() -> None:
    stamps = [utcnow() for _ in range(2000)]
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:]))
    assert stamps[0].tzinfo is not None


def test_element_ids_are_prefixed_and_unique() -> None:
    ids = {new_element_id("cls") for _ in range(500)}
    assert len(ids) == 500 and all(i.startswith("cls_") for i in ids)
