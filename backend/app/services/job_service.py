from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from app.domain.models import Job, UploadKind
from app.storage.base import StorageProvider


class JobNotFoundError(LookupError):
    pass


class JobService:
    """Owns job lifecycle and lightweight file-based metadata."""

    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage
        self._metadata_lock = Lock()

    def create_job(self) -> Job:
        job_id = str(uuid4())
        created_at = datetime.now(UTC)
        for folder in ("uploads", "processed", "results", "exports"):
            self.storage.create_directory(f"jobs/{job_id}/{folder}")
        metadata: dict[str, Any] = {
            "job_id": job_id,
            "created_at": created_at.isoformat(),
            "uploads": {},
        }
        self._save_metadata(job_id, metadata)
        return self._to_domain(metadata)

    def get_job(self, job_id: str) -> Job:
        return self._to_domain(self._load_metadata(job_id))

    def require_job(self, job_id: str) -> Job:
        return self._to_domain(self._load_metadata(job_id))

    def record_upload(self, job_id: str, kind: UploadKind, file_names: list[str]) -> None:
        with self._metadata_lock:
            metadata = self._load_metadata(job_id)
            uploads = metadata.setdefault("uploads", {})
            existing = uploads.setdefault(kind.value, [])
            for file_name in file_names:
                if file_name not in existing:
                    existing.append(file_name)
            self._save_metadata(job_id, metadata)

    def delete_job(self, job_id: str) -> Job:
        metadata = self._load_metadata(job_id)
        job = self._to_domain(metadata)
        self.storage.delete_directory(f"jobs/{job_id}")
        return job

    def _metadata_path(self, job_id: str) -> str:
        try:
            normalized_job_id = str(UUID(job_id))
        except ValueError as error:
            raise JobNotFoundError(f"Job '{job_id}' was not found") from error
        return f"jobs/{normalized_job_id}/job.json"

    def _load_metadata(self, job_id: str) -> dict[str, Any]:
        path = self._metadata_path(job_id)
        if not self.storage.exists(path):
            raise JobNotFoundError(f"Job '{job_id}' was not found")
        return self.storage.load_json(path)

    def _save_metadata(self, job_id: str, metadata: dict[str, Any]) -> None:
        self.storage.save_json(self._metadata_path(job_id), metadata)

    @staticmethod
    def _to_domain(metadata: dict[str, Any]) -> Job:
        return Job(
            job_id=metadata["job_id"],
            created_at=datetime.fromisoformat(metadata["created_at"]),
            uploads=metadata.get("uploads", {}),
        )
