import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from app.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    """Filesystem implementation constrained to a configured storage root."""

    _chunk_size = 1024 * 1024

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_directory(self, relative_path: str) -> None:
        self._resolve(relative_path).mkdir(parents=True, exist_ok=True)

    def save_file(self, relative_path: str, source: BinaryIO) -> int:
        destination = self._resolve(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with destination.open("wb") as target:
            while chunk := source.read(self._chunk_size):
                target.write(chunk)
                bytes_written += len(chunk)
        return bytes_written

    def load_file(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).read_bytes()

    def save_json(self, relative_path: str, value: dict[str, Any]) -> None:
        destination = self._resolve(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(destination)

    def load_json(self, relative_path: str) -> dict[str, Any]:
        payload = json.loads(self._resolve(relative_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object at {relative_path}")
        return payload

    def list_files(self, relative_path: str) -> list[str]:
        directory = self._resolve(relative_path)
        if not directory.exists():
            return []
        return sorted(str(path.relative_to(self.root)) for path in directory.rglob("*") if path.is_file())

    def delete_directory(self, relative_path: str) -> None:
        directory = self._resolve(relative_path)
        if directory == self.root:
            raise ValueError("Refusing to delete the storage root")
        if directory.exists():
            shutil.rmtree(directory)

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()

    def _resolve(self, relative_path: str) -> Path:
        candidate_path = PurePosixPath(relative_path)
        if candidate_path.is_absolute() or ".." in candidate_path.parts:
            raise ValueError("Storage paths must be relative and cannot traverse parents")
        candidate = (self.root / Path(*candidate_path.parts)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Storage path escapes the configured root")
        return candidate
