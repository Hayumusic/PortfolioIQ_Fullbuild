from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from app.domain.cmdb import ParsedCMDB
from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.file_service import FileService
from app.services.job_service import JobService
from app.storage.base import StorageProvider


class TeamValidationService:
    """Perform bounded, deterministic checks on the latest team-validation table."""

    application_code_aliases = (
        "application code",
        "app code",
        "application_code",
        "app_code",
    )
    yes_no_column_aliases = (
        "confirmed in use",
        "in use",
        "validated",
        "confirmed",
        "active",
        "reviewed",
    )
    valid_yes_no_values = {"yes", "no", "y", "n", "true", "false", "1", "0"}

    def __init__(
        self,
        storage: StorageProvider,
        job_service: JobService,
        file_service: FileService,
    ) -> None:
        self.storage = storage
        self.job_service = job_service
        self.file_service = file_service

    def analyze(self, job_id: str, parsed_cmdb: ParsedCMDB) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        uploads = job.uploads.get(UploadKind.TEAM_VALIDATION.value, [])
        if not uploads:
            return self.unavailable_summary()

        upload_id = uploads[-1]
        metadata = self.file_service.get_upload_metadata(
            job_id, UploadKind.TEAM_VALIDATION, upload_id
        )
        if not metadata.get("processed"):
            return self.unavailable_summary(upload_id=upload_id)

        path = f"jobs/{job_id}/uploads/{UploadKind.TEAM_VALIDATION.value}/{upload_id}"
        frame = self._parse_table(self.storage.load_file(path), upload_id)
        columns = [str(column).strip() for column in frame.columns]
        frame.columns = columns
        application_code_column = self._find_column(
            columns, self.application_code_aliases
        )
        yes_no_column = self._find_column(columns, self.yes_no_column_aliases)

        team_codes: set[str] = set()
        present_count = 0
        missing_count = 0
        unmatched_count = 0
        cmdb_codes = self._cmdb_codes(parsed_cmdb)
        if application_code_column is not None:
            for value in frame[application_code_column].tolist():
                code = self._text(value)
                if code is None:
                    missing_count += 1
                    continue
                present_count += 1
                normalized = code.casefold()
                team_codes.add(normalized)
                if normalized not in cmdb_codes:
                    unmatched_count += 1
        else:
            missing_count = len(frame.index)

        missing_cmdb_count = 0
        for application in parsed_cmdb.applications:
            code = (
                self._text(application.source_data.get(parsed_cmdb.application_code_column))
                if parsed_cmdb.application_code_column
                else None
            )
            if code is None or code.casefold() not in team_codes:
                missing_cmdb_count += 1

        invalid_yes_no_count = 0
        if yes_no_column is not None:
            invalid_yes_no_count = sum(
                1
                for value in frame[yes_no_column].tolist()
                if self._yes_no_value(value) not in self.valid_yes_no_values
            )

        return {
            "team_validation_available": True,
            "upload_id": upload_id,
            "row_count": len(frame.index),
            "column_count": len(columns),
            "columns": columns,
            "application_code_column": application_code_column,
            "rows_with_application_code": present_count,
            "rows_missing_application_code": missing_count,
            "unmatched_team_validation_records": unmatched_count,
            "cmdb_applications_missing_team_validation_record": missing_cmdb_count,
            "yes_no_column": yes_no_column,
            "invalid_yes_no_value_count": invalid_yes_no_count,
        }

    @staticmethod
    def unavailable_summary(upload_id: str | None = None) -> dict[str, Any]:
        return {
            "team_validation_available": False,
            "upload_id": upload_id,
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "application_code_column": None,
            "rows_with_application_code": 0,
            "rows_missing_application_code": 0,
            "unmatched_team_validation_records": 0,
            "cmdb_applications_missing_team_validation_record": 0,
            "yes_no_column": None,
            "invalid_yes_no_value_count": 0,
        }

    @staticmethod
    def _parse_table(content: bytes, file_name: str) -> pd.DataFrame:
        extension = Path(file_name).suffix.lower()
        source = BytesIO(content)
        if extension == ".csv":
            frame = pd.read_csv(source, dtype=object)
        else:
            engine = "openpyxl" if extension == ".xlsx" else "xlrd"
            frame = pd.read_excel(source, sheet_name=0, engine=engine, dtype=object)
        return frame.dropna(axis=0, how="all")

    @classmethod
    def _find_column(
        cls, columns: list[str], aliases: tuple[str, ...]
    ) -> str | None:
        by_normalized = {
            CMDBParserService.normalize_header(column): column for column in columns
        }
        for alias in aliases:
            match = by_normalized.get(CMDBParserService.normalize_header(alias))
            if match is not None:
                return match
        return None

    @classmethod
    def _cmdb_codes(cls, parsed: ParsedCMDB) -> set[str]:
        if parsed.application_code_column is None:
            return set()
        return {
            text.casefold()
            for application in parsed.applications
            if (text := cls._text(
                application.source_data.get(parsed.application_code_column)
            )) is not None
        }

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _yes_no_value(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip().casefold()
