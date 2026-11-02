from datetime import UTC, datetime
import mimetypes
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.domain.models import UploadBatchResult, UploadKind
from app.services.job_service import JobService
from app.storage.base import StorageProvider


class UploadValidationError(ValueError):
    pass


class FileService:
    """Validates upload metadata and streams accepted files to storage."""

    _allowed_extensions = {
        UploadKind.CMDB: {".xlsx", ".xls"},
        UploadKind.MANDATORY_FIELDS_CONFIG: {".xlsx", ".xls", ".csv"},
        UploadKind.OUTPUT_FAMILY_CONFIG: {".xlsx", ".xls", ".csv"},
        UploadKind.CONFLUENCE: {".pdf"},
        UploadKind.TEAM_VALIDATION: {".xlsx", ".xls", ".csv"},
        UploadKind.VALIDATION: {".xlsx", ".xls"},
        UploadKind.CLOUDWATCH: {".xlsx", ".xls", ".csv"},
    }

    def __init__(
        self,
        storage: StorageProvider,
        job_service: JobService,
        max_upload_bytes: int,
    ) -> None:
        self.storage = storage
        self.job_service = job_service
        self.max_upload_bytes = max_upload_bytes

    def save_upload(
        self,
        job_id: str,
        kind: UploadKind,
        original_name: str | None,
        source: BinaryIO,
        *,
        already_validated: bool = False,
    ) -> str:
        self.job_service.require_job(job_id)
        if not already_validated:
            self.validate_upload(kind, original_name, source)

        safe_name = Path(original_name or "").name
        stored_name = f"{uuid4().hex}_{safe_name}"
        path = f"jobs/{job_id}/uploads/{kind.value}/{stored_name}"
        size_bytes = self.storage.save_file(path, source)
        self.job_service.record_upload(job_id, kind, [stored_name])
        self.storage.save_json(
            self.upload_metadata_path(job_id, kind, stored_name),
            {
                "upload_id": stored_name,
                "filename": safe_name,
                "stored_filename": stored_name,
                "content_type": mimetypes.guess_type(safe_name)[0],
                "size_bytes": size_bytes,
                "uploaded_at": datetime.now(UTC).isoformat(),
                "warnings": [],
            },
        )
        return stored_name

    @staticmethod
    def upload_metadata_path(job_id: str, kind: UploadKind, upload_id: str) -> str:
        return f"jobs/{job_id}/processed/upload_metadata/{kind.value}/{upload_id}.json"

    def get_upload_metadata(
        self, job_id: str, kind: UploadKind, upload_id: str
    ) -> dict[str, object]:
        path = self.upload_metadata_path(job_id, kind, upload_id)
        if self.storage.exists(path):
            return self.storage.load_json(path)
        # Uploads created before metadata manifests existed remain visible.
        original_name = upload_id.split("_", 1)[1] if "_" in upload_id else upload_id
        return {
            "upload_id": upload_id,
            "filename": original_name,
            "stored_filename": upload_id,
            "content_type": mimetypes.guess_type(original_name)[0],
            "size_bytes": None,
            "uploaded_at": None,
            "warnings": [],
        }

    def update_upload_metadata(
        self,
        job_id: str,
        kind: UploadKind,
        upload_id: str,
        **values: object,
    ) -> dict[str, object]:
        metadata = self.get_upload_metadata(job_id, kind, upload_id)
        metadata.update(values)
        self.storage.save_json(
            self.upload_metadata_path(job_id, kind, upload_id), metadata
        )
        return metadata

    def validate_upload(
        self,
        kind: UploadKind,
        original_name: str | None,
        source: BinaryIO,
    ) -> int:
        safe_name = Path(original_name or "").name
        extension = Path(safe_name).suffix.lower()
        if not safe_name or extension not in self._allowed_extensions[kind]:
            allowed = ", ".join(sorted(self._allowed_extensions[kind]))
            raise UploadValidationError(f"{kind.value} uploads must use: {allowed}")

        source.seek(0, 2)
        size = source.tell()
        source.seek(0)
        if size == 0:
            raise UploadValidationError("Uploaded files cannot be empty")
        if size > self.max_upload_bytes:
            raise UploadValidationError("Uploaded file exceeds the configured size limit")
        return size

    def save_upload_batch(
        self,
        job_id: str,
        kind: UploadKind,
        uploads: list[tuple[str | None, BinaryIO]],
    ) -> UploadBatchResult:
        """Store an upload request as a batch and return a domain result."""

        # TODO: Stage all files before committing storage and job metadata so a
        # partial failure can roll back the entire batch.
        stored_names = [
            self.save_upload(job_id, kind, original_name, source)
            for original_name, source in uploads
        ]
        return UploadBatchResult(job_id=job_id, kind=kind, file_names=stored_names)
