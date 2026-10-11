import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return str(uuid.uuid4())


def new_element_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)
