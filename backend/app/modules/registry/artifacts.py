"""Write-once storage for published ontology artifacts."""

import hashlib
import os
import shutil
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class ArtifactIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    format: str
    filename: str
    path: str
    media_type: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class OntologyArtifactRepository(Protocol):
    def store(
        self, ontology_id: str, version_id: str, *, fmt: str, filename: str, media_type: str, content: bytes
    ) -> StoredArtifact: ...

    def read(self, artifact: StoredArtifact) -> bytes: ...

    def discard(self, ontology_id: str, version_id: str) -> None:
        """Remove artifacts of a version whose publication did not commit."""
        ...


class FilesystemArtifactRepository:
    """Stores artifacts under ``root/<ontology>/<version>/``. Files are created exclusively, made
    read-only and verified against their SHA-256 digest on every read."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, ontology_id: str, version_id: str) -> Path:
        return self.root / ontology_id / version_id

    def store(
        self, ontology_id: str, version_id: str, *, fmt: str, filename: str, media_type: str, content: bytes
    ) -> StoredArtifact:
        directory = self._dir(ontology_id, version_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        with open(path, "xb") as handle:
            handle.write(content)
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        return StoredArtifact(
            format=fmt,
            filename=filename,
            path=path.relative_to(self.root).as_posix(),
            media_type=media_type,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
        )

    def read(self, artifact: StoredArtifact) -> bytes:
        path = (self.root / artifact.path).resolve()
        if self.root.resolve() not in path.parents:
            raise ArtifactIntegrityError("Artifact path is outside the artifact store.")
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactIntegrityError(f"Artifact '{artifact.filename}' is missing from the artifact store.") from error
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ArtifactIntegrityError(f"Artifact '{artifact.filename}' does not match its recorded checksum.")
        return content

    def discard(self, ontology_id: str, version_id: str) -> None:
        directory = self._dir(ontology_id, version_id)
        if not directory.exists():
            return
        for path in directory.iterdir():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        shutil.rmtree(directory, ignore_errors=True)
