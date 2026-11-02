from app.services.cmdb_parser_service import CMDBParserService
from app.storage.base import StorageProvider


class MandatoryFieldConfigError(ValueError):
    pass


class MandatoryFieldConfigService:
    config_path = "config/cmdb_mandatory_fields.json"

    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage

    def set_fields(self, fields: list[str]) -> list[str]:
        cleaned = [field.strip() for field in fields if isinstance(field, str) and field.strip()]
        if not cleaned:
            raise MandatoryFieldConfigError(
                "At least one non-empty mandatory CMDB field is required"
            )
        normalized = [CMDBParserService.normalize_header(field) for field in cleaned]
        if any(not field for field in normalized):
            raise MandatoryFieldConfigError(
                "Mandatory CMDB fields must contain letters or numbers"
            )
        if len(set(normalized)) != len(normalized):
            raise MandatoryFieldConfigError(
                "Mandatory CMDB fields must be unique after normalized matching"
            )
        self.storage.save_json(self.config_path, {"mandatory_fields": cleaned})
        return cleaned

    def get_fields(self, required: bool = False) -> list[str]:
        if not self.storage.exists(self.config_path):
            if required:
                raise MandatoryFieldConfigError(
                    "CMDB validation requires mandatory fields to be configured first"
                )
            return []
        value = self.storage.load_json(self.config_path).get("mandatory_fields", [])
        if not isinstance(value, list):
            raise MandatoryFieldConfigError("Stored mandatory-field configuration is invalid")
        return self.set_fields_in_memory(value)

    def set_job_fields(
        self,
        job_id: str,
        fields: list[str],
        *,
        upload_id: str,
        row_count: int,
        warnings: list[str],
    ) -> list[str]:
        cleaned = self.set_fields_in_memory(fields)
        self.storage.save_json(
            self.job_config_path(job_id),
            {
                "upload_id": upload_id,
                "mandatory_fields": cleaned,
                "row_count": row_count,
                "warnings": warnings,
                "usable": True,
            },
        )
        return cleaned

    def get_job_fields(self, job_id: str, required: bool = False) -> list[str]:
        path = self.job_config_path(job_id)
        if not self.storage.exists(path):
            if required:
                raise MandatoryFieldConfigError(
                    "No usable mandatory-fields configuration exists for this job"
                )
            return []
        value = self.storage.load_json(path).get("mandatory_fields", [])
        if not isinstance(value, list):
            raise MandatoryFieldConfigError(
                "Stored job mandatory-field configuration is invalid"
            )
        return self.set_fields_in_memory(value)

    def get_effective_fields(self, job_id: str, required: bool = False) -> list[str]:
        return self.get_effective_config(job_id, required=required)["mandatory_fields"]

    def get_effective_config(
        self, job_id: str, required: bool = False
    ) -> dict[str, object]:
        path = self.job_config_path(job_id)
        if self.storage.exists(path):
            job_config = self.storage.load_json(path)
            if job_config.get("usable", True):
                try:
                    job_fields = self.get_job_fields(job_id, required=False)
                except MandatoryFieldConfigError:
                    job_fields = []
                if job_fields:
                    return {
                        "mandatory_fields": job_fields,
                        "source": "job_upload",
                        "upload_id": job_config.get("upload_id"),
                    }
        global_fields = self.get_fields(required=required)
        return {
            "mandatory_fields": global_fields,
            "source": "global_config" if global_fields else "default_or_missing",
            "upload_id": None,
        }

    @staticmethod
    def job_config_path(job_id: str) -> str:
        return f"jobs/{job_id}/processed/config/mandatory_fields.json"

    def set_fields_in_memory(self, fields: list[object]) -> list[str]:
        if not all(isinstance(field, str) for field in fields):
            raise MandatoryFieldConfigError("Mandatory CMDB fields must be strings")
        cleaned = [field.strip() for field in fields if field.strip()]
        if not cleaned:
            raise MandatoryFieldConfigError(
                "At least one non-empty mandatory CMDB field is required"
            )
        normalized = [CMDBParserService.normalize_header(field) for field in cleaned]
        if any(not field for field in normalized) or len(set(normalized)) != len(normalized):
            raise MandatoryFieldConfigError("Stored mandatory-field configuration is invalid")
        return cleaned
