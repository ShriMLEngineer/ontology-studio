import threading
import uuid
from datetime import UTC, datetime, timedelta

_clock_lock = threading.Lock()
_last_timestamp = datetime.min.replace(tzinfo=UTC)


def new_id() -> str:
    return str(uuid.uuid4())


def new_element_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Current UTC time, strictly increasing within the process.

    Some platforms (e.g. Windows) advance the wall clock in ~15 ms steps; making timestamps
    unique keeps audit trails and histories in true creation order.
    """
    global _last_timestamp
    with _clock_lock:
        now = datetime.now(UTC)
        if now <= _last_timestamp:
            now = _last_timestamp + timedelta(microseconds=1)
        _last_timestamp = now
        return now
