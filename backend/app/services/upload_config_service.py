from __future__ import annotations

from pathlib import Path
import re
from typing import Any, BinaryIO

import pandas as pd

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.file_service import FileService
from app.services.job_service import JobService
from app.services.mandatory_field_config_service import MandatoryFieldConfigService
from app.storage.base import StorageProvider


class UploadConfigParseError(ValueError):
    pass


class UploadConfigService:
    """Parse job-scoped configuration and describe all Phase A inputs."""

    mandatory_field_aliases = (
        "mandatory_field",
        "mandatory fields",
        "field",
        "field_name",
        "cmdb_field",
        "cmdb column",
        "column",
    )
    family_aliases = (
        "output_family",
        "output family",
        "family",
        "family_name",
        "output",
        "output_name",
    )
    keyword_aliases = ("keywords", "patterns")
    description_aliases = ("description",)
    family_key_aliases = ("family_key", "family key", "output_family_key", "output family key")
    member_aliases = ("members", "member", "applications", "application")
    member_code_aliases = (
        "application_code",
        "application code",
        "app_code",
        "app code",
        "application_id",
        "application id",
    )
    member_name_aliases = (
        "application_name",
        "application name",
        "app_name",
        "app name",
    )
    output_family_path_template = "jobs/{job_id}/processed/config/output_families.json"
    preview_limit = 20

    accepted_types: dict[UploadKind, list[str]] = {
        UploadKind.CMDB: [".xlsx", ".xls"],
        UploadKind.MANDATORY_FIELDS_CONFIG: [".xlsx", ".xls", ".csv"],
        UploadKind.OUTPUT_FAMILY_CONFIG: [".xlsx", ".xls", ".csv"],
        UploadKind.CONFLUENCE: [".pdf"],
        UploadKind.TEAM_VALIDATION: [".xlsx", ".xls", ".csv"],
        UploadKind.CLOUDWATCH: [".xlsx", ".xls", ".csv"],
    }

    def __init__(
        self,
        storage: StorageProvider,
        job_service: JobService,
        file_service: FileService,
        mandatory_config_service: MandatoryFieldConfigService,
    ) -> None:
        self.storage = storage
        self.job_service = job_service
        self.file_service = file_service
        self.mandatory_config_service = mandatory_config_service

    def upload_mandatory_fields_config(
        self, job_id: str, original_name: str | None, source: BinaryIO
    ) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        name = original_name or ""
        self.file_service.validate_upload(
            UploadKind.MANDATORY_FIELDS_CONFIG, name, source
        )
        frame = self._parse_table(source, name, "mandatory-fields configuration")
        fields, warnings = self._mandatory_fields(frame)
        if not fields:
            raise UploadConfigParseError(
                "Mandatory-fields configuration contains no usable mandatory fields"
            )
        upload_id = self.file_service.save_upload(
            job_id,
            UploadKind.MANDATORY_FIELDS_CONFIG,
            name,
            source,
            already_validated=True,
        )
        fields = self.mandatory_config_service.set_job_fields(
            job_id,
            fields,
            upload_id=upload_id,
            row_count=len(frame.index),
            warnings=warnings,
        )
        file_metadata = self.file_service.update_upload_metadata(
            job_id,
            UploadKind.MANDATORY_FIELDS_CONFIG,
            upload_id,
            processed=True,
            row_count=len(frame.index),
            column_count=len(frame.columns),
            warnings=warnings,
        )
        return {
            "job_id": job_id,
            "upload_id": upload_id,
            "file": file_metadata,
            "configured_mandatory_fields": fields,
            "row_count": len(frame.index),
            "warnings": warnings,
            "usable": True,
        }

    def upload_output_family_config(
        self, job_id: str, original_name: str | None, source: BinaryIO
    ) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        name = original_name or ""
        self.file_service.validate_upload(
            UploadKind.OUTPUT_FAMILY_CONFIG, name, source
        )
        frame = self._parse_table(source, name, "output-family configuration")
        families, warnings = self._output_families(frame)
        if not families:
            raise UploadConfigParseError(
                "Output-family configuration contains no usable output families"
            )
        upload_id = self.file_service.save_upload(
            job_id,
            UploadKind.OUTPUT_FAMILY_CONFIG,
            name,
            source,
            already_validated=True,
        )
        payload = {
            "upload_id": upload_id,
            "family_count": len(families),
            "families": families,
            "row_count": len(frame.index),
            "warnings": warnings,
            "usable": True,
        }
        self.storage.save_json(
            self.output_family_path_template.format(job_id=job_id), payload
        )
        file_metadata = self.file_service.update_upload_metadata(
            job_id,
            UploadKind.OUTPUT_FAMILY_CONFIG,
            upload_id,
            processed=True,
            row_count=len(frame.index),
            column_count=len(frame.columns),
            warnings=warnings,
        )
        return {"job_id": job_id, "file": file_metadata, **payload}

    def upload_confluence(
        self,
        job_id: str,
        uploads: list[tuple[str | None, BinaryIO]],
    ) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        if not uploads:
            raise UploadConfigParseError("At least one Confluence PDF is required")
        for name, source in uploads:
            self.file_service.validate_upload(UploadKind.CONFLUENCE, name, source)

        files: list[dict[str, object]] = []
        for name, source in uploads:
            upload_id = self.file_service.save_upload(
                job_id,
                UploadKind.CONFLUENCE,
                name,
                source,
                already_validated=True,
            )
            files.append(
                self.file_service.update_upload_metadata(
                    job_id,
                    UploadKind.CONFLUENCE,
                    upload_id,
                    processed=True,
                    page_count=None,
                    warnings=[],
                )
            )
        return {
            "job_id": job_id,
            "upload_id": files[-1]["upload_id"],
            "upload_kind": UploadKind.CONFLUENCE,
            "files": files,
            "file_count": len(files),
            "row_count": None,
            "column_count": None,
            "columns": [],
            "warnings": [],
            "processed": True,
            "stored_for_future_analysis": True,
        }

    def upload_supporting_table(
        self,
        job_id: str,
        kind: UploadKind,
        original_name: str | None,
        source: BinaryIO,
    ) -> dict[str, Any]:
        if kind not in {UploadKind.TEAM_VALIDATION, UploadKind.CLOUDWATCH}:
            raise ValueError(f"Unsupported supporting upload kind: {kind.value}")
        self.job_service.require_job(job_id)
        name = original_name or ""
        self.file_service.validate_upload(kind, name, source)
        frame = self._parse_table(source, name, kind.value.replace("_", " "))
        upload_id = self.file_service.save_upload(
            job_id, kind, name, source, already_validated=True
        )
        columns = [str(column).strip() for column in frame.columns]
        preview = {
            "upload_id": upload_id,
            "row_count": len(frame.index),
            "column_count": len(columns),
            "columns": columns,
            "preview_row_limit": min(len(frame.index), self.preview_limit),
            "preview": [
                {
                    column: self._json_value(value)
                    for column, value in row.items()
                }
                for row in frame.head(self.preview_limit).to_dict(orient="records")
            ],
        }
        self.storage.save_json(
            f"jobs/{job_id}/processed/{kind.value}_preview.json", preview
        )
        file_metadata = self.file_service.update_upload_metadata(
            job_id,
            kind,
            upload_id,
            processed=True,
            row_count=preview["row_count"],
            column_count=preview["column_count"],
            columns=columns,
            warnings=[],
        )
        return {
            "job_id": job_id,
            "upload_id": upload_id,
            "upload_kind": kind,
            "files": [file_metadata],
            "file_count": 1,
            "row_count": preview["row_count"],
            "column_count": preview["column_count"],
            "columns": columns,
            "warnings": [],
            "processed": True,
            "stored_for_future_analysis": True,
        }

    def get_mandatory_fields_config(self, job_id: str) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        path = self.mandatory_config_service.job_config_path(job_id)
        if self.storage.exists(path):
            return self.storage.load_json(path)
        fields = self.mandatory_config_service.get_fields(required=False)
        return {
            "upload_id": None,
            "mandatory_fields": fields,
            "row_count": 0,
            "warnings": (
                ["Using the existing global mandatory-fields configuration."]
                if fields
                else ["Mandatory fields have not been configured."]
            ),
            "usable": bool(fields),
        }

    def get_output_families_config(self, job_id: str) -> dict[str, Any]:
        self.job_service.require_job(job_id)
        path = self.output_family_path_template.format(job_id=job_id)
        if self.storage.exists(path):
            return self.storage.load_json(path)
        return {
            "upload_id": None,
            "family_count": 0,
            "families": [],
            "row_count": 0,
            "warnings": ["Output families have not been configured for this job."],
            "usable": False,
        }

    def get_upload_status(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        mandatory = self.get_mandatory_fields_config(job_id)
        output_families = self.get_output_families_config(job_id)

        sources = {
            "cmdb": self._source_status(job_id, job.uploads, UploadKind.CMDB, True),
            "mandatory_fields_config": self._source_status(
                job_id, job.uploads, UploadKind.MANDATORY_FIELDS_CONFIG, True
            ),
            "output_family_config": self._source_status(
                job_id, job.uploads, UploadKind.OUTPUT_FAMILY_CONFIG, True
            ),
            "confluence": self._source_status(
                job_id, job.uploads, UploadKind.CONFLUENCE, False
            ),
            "team_validation": self._source_status(
                job_id, job.uploads, UploadKind.TEAM_VALIDATION, False
            ),
            "cloudwatch": self._source_status(
                job_id, job.uploads, UploadKind.CLOUDWATCH, False
            ),
        }
        cmdb_ready = bool(sources["cmdb"]["uploaded"] and sources["cmdb"]["processed"])
        mandatory_ready = bool(mandatory["usable"])
        output_ready = bool(output_families["usable"])
        optional_available = any(
            bool(sources[name]["uploaded"])
            for name in ("confluence", "team_validation", "cloudwatch")
        )
        missing_required = [
            name
            for name, ready in (
                ("cmdb", cmdb_ready),
                ("mandatory_fields_config", mandatory_ready),
                ("output_family_config", output_ready),
            )
            if not ready
        ]
        warnings: list[str] = []
        if not cmdb_ready:
            warnings.append("CMDB upload is required.")
        if not mandatory_ready:
            warnings.append("Mandatory-fields configuration is required for validation.")
        elif not sources["mandatory_fields_config"]["uploaded"]:
            warnings.append("Validation will use the existing global mandatory-fields configuration.")
        if not output_ready:
            warnings.append("Output-family configuration is required for outputs analysis.")
        return {
            "job_id": job_id,
            "sources": sources,
            "cmdb_ready": cmdb_ready,
            "mandatory_fields_config_ready": mandatory_ready,
            "output_family_config_ready": output_ready,
            "optional_inputs_available": optional_available,
            "can_run_validation": cmdb_ready and mandatory_ready,
            "can_run_outputs_analysis": cmdb_ready and output_ready,
            "missing_required_inputs": missing_required,
            "warnings": warnings,
        }

    def _source_status(
        self,
        job_id: str,
        uploads: dict[str, list[str]],
        kind: UploadKind,
        required: bool,
    ) -> dict[str, Any]:
        upload_ids = uploads.get(kind.value, [])
        latest_id = upload_ids[-1] if upload_ids else None
        metadata = (
            self.file_service.get_upload_metadata(job_id, kind, latest_id)
            if latest_id
            else {}
        )
        processed = bool(metadata.get("processed", False))
        if kind == UploadKind.CMDB and latest_id:
            preview_path = f"jobs/{job_id}/processed/cmdb_preview.json"
            processed = self.storage.exists(preview_path) and (
                self.storage.load_json(preview_path).get("upload_id") == latest_id
            )
        return {
            "required": required,
            "uploaded": bool(upload_ids),
            "processed": processed,
            "upload_count": len(upload_ids),
            "latest_upload_id": latest_id,
            "latest_filename": metadata.get("filename"),
            "accepted_file_types": self.accepted_types[kind],
            "warnings": metadata.get("warnings", []),
        }

    @classmethod
    def _mandatory_fields(cls, frame: pd.DataFrame) -> tuple[list[str], list[str]]:
        column = cls._find_column(frame, cls.mandatory_field_aliases)
        if column is None and len(frame.columns) == 1:
            column = frame.columns[0]
        if column is None:
            raise UploadConfigParseError(
                "Mandatory-fields configuration needs a supported field-name column"
            )
        warnings: list[str] = []
        fields: list[str] = []
        seen: set[str] = set()
        duplicate_count = 0
        for value in frame[column].tolist():
            text = cls._text(value)
            if not text:
                continue
            normalized = CMDBParserService.normalize_header(text)
            if not normalized:
                continue
            if normalized in seen:
                duplicate_count += 1
                continue
            seen.add(normalized)
            fields.append(text)
        if duplicate_count:
            warnings.append(
                f"Removed {duplicate_count} duplicate mandatory-field entr"
                f"{'y' if duplicate_count == 1 else 'ies'}."
            )
        return fields, warnings

    @classmethod
    def _output_families(
        cls, frame: pd.DataFrame
    ) -> tuple[list[dict[str, Any]], list[str]]:
        family_column = cls._find_column(frame, cls.family_aliases)
        if family_column is None and len(frame.columns) == 1:
            family_column = frame.columns[0]
        if family_column is None:
            raise UploadConfigParseError(
                "Output-family configuration needs a supported family column"
            )
        keyword_column = cls._find_column(frame, cls.keyword_aliases)
        description_column = cls._find_column(frame, cls.description_aliases)
        family_key_column = cls._find_column(frame, cls.family_key_aliases)
        member_column = cls._find_column(frame, cls.member_aliases)
        member_code_column = cls._find_column(frame, cls.member_code_aliases)
        member_name_column = cls._find_column(frame, cls.member_name_aliases)
        families: list[dict[str, Any]] = []
        by_name: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        for _, row in frame.iterrows():
            name = cls._text(row.get(family_column))
            if not name:
                continue
            key = name.casefold()
            keywords = cls._split_keywords(
                row.get(keyword_column) if keyword_column is not None else None
            )
            member_code = cls._text(
                row.get(member_code_column) if member_code_column is not None else None
            )
            member_name = cls._text(
                row.get(member_name_column) if member_name_column is not None else None
            )
            member_values = cls._split_keywords(
                row.get(member_column) if member_column is not None else None
            )
            # Keep the Phase A response/storage contract where a ``Members``
            # column was exposed through ``keywords``, while also preserving
            # those values as explicit members for deterministic Phase E use.
            if member_values:
                keywords = cls._deduplicate_text([*keywords, *member_values])
            members: list[dict[str, str | None]] = []
            if member_code or member_name:
                members.append(
                    {
                        "application_code": member_code,
                        "application_name": member_name,
                        "member_value": None,
                    }
                )
            members.extend(
                {
                    "application_code": None,
                    "application_name": None,
                    "member_value": value,
                }
                for value in member_values
            )
            description = cls._text(
                row.get(description_column)
                if description_column is not None
                else None
            )
            if key in by_name:
                duplicate_count += 1
                existing = by_name[key]
                existing["keywords"] = cls._deduplicate_text(
                    [*existing["keywords"], *keywords]
                )
                existing["members"].extend(members)
                if not existing["description"] and description:
                    existing["description"] = description
                if not existing.get("key") and family_key_column is not None:
                    existing["key"] = cls._text(row.get(family_key_column))
                continue
            family = {
                "key": (
                    cls._text(row.get(family_key_column))
                    if family_key_column is not None
                    else None
                ),
                "name": name,
                "keywords": keywords,
                "description": description,
                "members": members,
            }
            by_name[key] = family
            families.append(family)
        warnings = []
        if duplicate_count:
            warnings.append(
                f"Merged {duplicate_count} duplicate output-family row"
                f"{'s' if duplicate_count != 1 else ''}."
            )
        if families and all(
            not item["keywords"] and not item["members"] for item in families
        ):
            warnings.append("No keywords, members, or patterns were configured.")
        return families, warnings

    @staticmethod
    def _parse_table(source: BinaryIO, file_name: str, label: str) -> pd.DataFrame:
        extension = Path(file_name).suffix.casefold()
        try:
            source.seek(0)
            if extension == ".csv":
                frame = pd.read_csv(source, dtype=object)
            else:
                engine = "openpyxl" if extension == ".xlsx" else "xlrd"
                frame = pd.read_excel(source, sheet_name=0, engine=engine, dtype=object)
        except Exception as error:
            raise UploadConfigParseError(
                f"The uploaded {label} could not be parsed"
            ) from error
        finally:
            source.seek(0)
        frame = frame.dropna(axis=0, how="all")
        frame.columns = [str(column).strip() for column in frame.columns]
        return frame

    @classmethod
    def _find_column(
        cls, frame: pd.DataFrame, aliases: tuple[str, ...]
    ) -> str | None:
        columns = {
            CMDBParserService.normalize_header(str(column)): str(column)
            for column in frame.columns
        }
        for alias in aliases:
            matched = columns.get(CMDBParserService.normalize_header(alias))
            if matched is not None:
                return matched
        return None

    @staticmethod
    def _text(value: object) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    @classmethod
    def _split_keywords(cls, value: object) -> list[str]:
        text = cls._text(value)
        if not text:
            return []
        return cls._deduplicate_text(re.split(r",", text))

    @staticmethod
    def _deduplicate_text(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    @staticmethod
    def _json_value(value: object) -> object:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
