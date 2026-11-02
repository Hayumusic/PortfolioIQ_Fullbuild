from io import BytesIO
import csv
from io import StringIO
from math import ceil
from typing import Any, BinaryIO

from app.domain.cmdb import ParsedCMDB
from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.cmdb_validation_service import CMDBValidationService
from app.services.file_service import FileService
from app.services.job_service import JobService
from app.services.mandatory_field_config_service import MandatoryFieldConfigService
from app.services.team_validation_service import TeamValidationService
from app.storage.base import StorageProvider


class CMDBNotUploadedError(ValueError):
    pass


class CMDBValidationResultNotFoundError(LookupError):
    pass


class CMDBService:
    """Coordinate CMDB upload, parsing, deterministic validation, and artifacts."""

    def __init__(
        self,
        storage: StorageProvider,
        job_service: JobService,
        file_service: FileService,
        parser_service: CMDBParserService,
        validation_service: CMDBValidationService,
        config_service: MandatoryFieldConfigService,
        team_validation_service: TeamValidationService | None = None,
    ) -> None:
        self.storage = storage
        self.job_service = job_service
        self.file_service = file_service
        self.parser_service = parser_service
        self.validation_service = validation_service
        self.config_service = config_service
        self.team_validation_service = team_validation_service or TeamValidationService(
            storage, job_service, file_service
        )

    def upload(self, job_id: str, original_name: str | None, source: BinaryIO) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        name = original_name or ""
        self.file_service.validate_upload(UploadKind.CMDB, name, source)
        parsed = self.parser_service.parse(source, name)
        upload_id = self.file_service.save_upload(
            job_id, UploadKind.CMDB, name, source, already_validated=True
        )
        self._save_preview(job_id, upload_id, parsed)
        file_metadata = self.file_service.update_upload_metadata(
            job_id,
            UploadKind.CMDB,
            upload_id,
            processed=True,
            row_count=parsed.row_count,
            column_count=parsed.column_count,
            columns=parsed.columns,
        )
        return {
            "upload_id": upload_id,
            "file_names": [upload_id],
            "file": file_metadata,
            "row_count": parsed.row_count,
            "column_count": parsed.column_count,
        }

    def run_validation(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        mandatory_config = self.config_service.get_effective_config(
            job_id, required=True
        )
        mandatory_fields = mandatory_config["mandatory_fields"]
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads:
            raise CMDBNotUploadedError(
                "CMDB validation requires a CMDB workbook to be uploaded first"
            )
        upload_id = uploads[-1]
        path = f"jobs/{job_id}/uploads/{UploadKind.CMDB.value}/{upload_id}"
        workbook = BytesIO(self.storage.load_file(path))
        parsed = self.parser_service.parse(workbook, upload_id)
        team_summary = self.team_validation_service.analyze(job_id, parsed)
        optional_input_summary = self._optional_input_summary(
            job_id, job.uploads, team_summary
        )
        result = self.validation_service.validate(
            parsed,
            mandatory_fields,
            upload_id,
            mandatory_fields_config_source=str(mandatory_config["source"]),
            mandatory_fields_config_upload_id=mandatory_config.get("upload_id"),
            optional_input_summary=optional_input_summary,
            team_validation_summary=team_summary,
        )
        stored_result = {"job_id": job_id, **result}
        self.storage.save_json(f"jobs/{job_id}/results/cmdb_validation.json", stored_result)
        return stored_result

    def get_validation(self, job_id: str) -> dict[str, Any]:
        return self._load_current_validation(job_id)

    def run_validation_overview(self, job_id: str) -> dict[str, Any]:
        result = self.run_validation(job_id)
        return self._validation_overview(job_id, result)

    def get_validation_overview(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_validation(job_id)
        return self._validation_overview(job_id, result)

    def _validation_overview(
        self, job_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        validation_status = result["validation_status"]
        details_endpoint = (
            f"/api/jobs/{job_id}/analysis/validation/details?page=1&page_size=50"
        )
        duplicates_endpoint = f"/api/jobs/{job_id}/analysis/validation/duplicates"
        completeness_csv_endpoint = (
            f"/api/jobs/{job_id}/analysis/validation/completeness.csv"
        )
        return {
            "status": "validated",
            "module_name": "validation",
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "validation_status": validation_status,
            "analysis_status": (
                "completed_with_warnings"
                if validation_status == "completed_with_warnings"
                else "completed"
            ),
            "summary": self._summary_metrics(result),
            "warnings": result.get("validation_warnings", []),
            "details_endpoint": details_endpoint,
            "duplicates_endpoint": duplicates_endpoint,
            "completeness_csv_endpoint": completeness_csv_endpoint,
            "detail_endpoints": {
                "details": details_endpoint,
                "duplicates": duplicates_endpoint,
                "completeness_csv": completeness_csv_endpoint,
            },
        }

    def get_validation_summary(self, job_id: str) -> dict[str, Any]:
        return self.get_validation_overview(job_id)

    def get_validation_details(
        self, job_id: str, page: int, page_size: int
    ) -> dict[str, Any]:
        result = self._load_current_validation(job_id)
        applications = result.get("applications", [])
        total_records = len(applications)
        total_pages = ceil(total_records / page_size) if total_records else 0
        start = (page - 1) * page_size
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
            "records": applications[start : start + page_size],
        }

    def get_validation_duplicates(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_validation(job_id)
        summary = result["summary"]
        duplicate_codes = summary.get(
            "duplicate_application_codes",
            summary.get("duplicate_application_ids", []),
        )
        duplicate_names = summary.get("duplicate_application_names", [])
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "duplicate_application_code_group_count": len(duplicate_codes),
            "duplicate_application_codes": duplicate_codes,
            # Backward-compatible duplicate identifier fields.
            "duplicate_application_id_group_count": len(duplicate_codes),
            "duplicate_application_name_group_count": len(duplicate_names),
            "duplicate_application_ids": duplicate_codes,
            "duplicate_application_names": duplicate_names,
        }

    def get_validation_completeness_csv(self, job_id: str) -> str:
        result = self._load_current_validation(job_id)
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "Application Code",
                "Application Name",
                "completeness_percentage",
                "missing_mandatory_fields",
                "source_of_truth_label",
                "reliability_label",
            ]
        )
        for application in result.get("applications", []):
            writer.writerow(
                [
                    application.get("application_code") or "",
                    application.get("application_name") or "",
                    (
                        ""
                        if application.get("completeness_percentage") is None
                        else application.get("completeness_percentage")
                    ),
                    "; ".join(application.get("missing_mandatory_fields", [])),
                    application.get("source_of_truth_label") or "",
                    application.get("reliability_label") or "",
                ]
            )
        return output.getvalue()

    def get_columns(self, job_id: str) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path):
            raise CMDBNotUploadedError(
                f"No parsed CMDB upload exists for job '{job_id}'"
            )
        preview = self.storage.load_json(path)
        return {
            "job_id": job_id,
            "upload_id": preview["upload_id"],
            "total_column_count": preview["total_column_count"],
            "columns": preview["columns"],
            "application_code_column": preview.get(
                "application_code_column", preview.get("application_id_column")
            ),
            "application_id_column": preview.get(
                "application_code_column", preview.get("application_id_column")
            ),
            "application_name_column": preview.get("application_name_column"),
        }

    def get_applications(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path):
            raise CMDBNotUploadedError(
                f"No parsed CMDB upload exists for job '{job_id}'"
            )

        preview = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or preview.get("upload_id") != uploads[-1]:
            raise CMDBNotUploadedError(
                f"No parsed CMDB upload exists for the current upload in job '{job_id}'"
            )

        code_column = preview.get("application_code_column") or preview.get(
            "application_id_column"
        )
        name_column = preview.get("application_name_column")
        applications = []
        for record in preview.get("applications", []):
            source_data = record.get("source_data", {})
            applications.append(
                {
                    "internal_row_number": record["internal_row_number"],
                    "application_code": self._optional_text(
                        source_data.get(code_column) if code_column else None
                    ),
                    "application_name": self._optional_text(
                        source_data.get(name_column) if name_column else None
                    ),
                }
            )

        return {
            "job_id": job_id,
            "upload_id": preview["upload_id"],
            "total_records": len(applications),
            "applications": applications,
        }

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _load_current_validation(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = f"jobs/{job_id}/results/cmdb_validation.json"
        if not self.storage.exists(path):
            raise CMDBValidationResultNotFoundError(
                f"CMDB validation has not been run for job '{job_id}'"
            )
        result = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or result.get("upload_id") != uploads[-1]:
            raise CMDBValidationResultNotFoundError(
                f"The latest CMDB upload for job '{job_id}' has not been validated"
            )
        return result

    @staticmethod
    def _summary_metrics(result: dict[str, Any]) -> dict[str, Any]:
        summary = result["summary"]
        return {
            "total_row_count": summary["total_row_count"],
            "total_column_count": summary["total_column_count"],
            "overall_completeness": summary["overall_completeness"],
            "matched_mandatory_columns": summary["matched_mandatory_columns"],
            "missing_mandatory_columns": summary["missing_mandatory_columns"],
            "mandatory_field_mappings": summary.get("mandatory_field_mappings", []),
            "mandatory_fields_config_source": summary.get(
                "mandatory_fields_config_source", "default_or_missing"
            ),
            "mandatory_fields_config_upload_id": summary.get(
                "mandatory_fields_config_upload_id"
            ),
            "application_code_column": summary.get(
                "application_code_column", summary.get("application_id_column")
            ),
            "application_id_column": summary.get(
                "application_code_column", summary.get("application_id_column")
            ),
            "duplicate_application_code_group_count": len(
                summary.get(
                    "duplicate_application_codes",
                    summary.get("duplicate_application_ids", []),
                )
            ),
            "duplicate_application_id_group_count": len(
                summary.get(
                    "duplicate_application_codes",
                    summary.get("duplicate_application_ids", []),
                )
            ),
            "duplicate_application_name_group_count": len(
                summary.get("duplicate_application_names", [])
            ),
            "warning_count": len(result.get("validation_warnings", [])),
            "missing_data_warnings": result.get("validation_warnings", []),
            "source_of_truth_label": summary.get("source_of_truth_label"),
            "reliability_label": summary.get("reliability_label"),
            "reliability_reason": summary.get(
                "reliability_reason", summary.get("reliability_note")
            ),
            "team_validation_summary": summary.get("team_validation_summary"),
            "optional_input_summary": summary.get("optional_input_summary"),
        }

    def _optional_input_summary(
        self,
        job_id: str,
        uploads: dict[str, list[str]],
        team_summary: dict[str, Any],
    ) -> dict[str, Any]:
        confluence_ids = uploads.get(UploadKind.CONFLUENCE.value, [])
        cloudwatch_ids = uploads.get(UploadKind.CLOUDWATCH.value, [])
        confluence_available = bool(confluence_ids)
        team_available = bool(team_summary.get("team_validation_available"))
        inputs_used = ["cmdb"]
        if confluence_available:
            inputs_used.append("confluence")
        if confluence_available and team_available:
            inputs_used.append("team_validation")
        return {
            "confluence_available": confluence_available,
            "confluence_file_count": len(confluence_ids),
            "team_validation_available": team_available,
            "team_validation_upload_id": team_summary.get("upload_id"),
            "cloudwatch_available": bool(cloudwatch_ids),
            "cloudwatch_upload_id": cloudwatch_ids[-1] if cloudwatch_ids else None,
            "source_of_truth_inputs_used": inputs_used,
        }

    def _save_preview(self, job_id: str, upload_id: str, parsed: ParsedCMDB) -> None:
        preview = {
            "upload_id": upload_id,
            "total_row_count": parsed.row_count,
            "total_column_count": parsed.column_count,
            "columns": parsed.columns,
            "application_code_column": parsed.application_code_column,
            "application_id_column": parsed.application_code_column,
            "application_name_column": parsed.application_name_column,
            # Upload parsing already enforces MAX_CMDB_ROWS. Keep every normalized
            # row so downstream CMDB-only analysis never silently analyzes a sample.
            "preview_row_limit": parsed.row_count,
            "applications": [
                {
                    "internal_row_number": item.internal_row_number,
                    "application_key": item.application_key,
                    "application_name": item.application_name,
                    "source_data": item.source_data,
                }
                for item in parsed.applications
            ],
        }
        self.storage.save_json(f"jobs/{job_id}/processed/cmdb_preview.json", preview)
