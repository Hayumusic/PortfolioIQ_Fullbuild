from collections import defaultdict
from typing import Any

from app.domain.cmdb import ParsedCMDB
from app.services.cmdb_parser_service import CMDBParserService


class CMDBValidationService:
    evidence_type = "Direct CMDB Evidence"
    source_of_truth_label = "Source of Truth 1"
    reliability_label = "Average"
    reliability_note = "Team validation is unavailable or mandatory completeness is below 70%."

    def validate(
        self,
        parsed: ParsedCMDB,
        mandatory_fields: list[str],
        upload_id: str,
        *,
        mandatory_fields_config_source: str = "default_or_missing",
        mandatory_fields_config_upload_id: str | None = None,
        optional_input_summary: dict[str, Any] | None = None,
        team_validation_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actual_by_normalized = {
            CMDBParserService.normalize_header(column): column for column in parsed.columns
        }
        matched: list[dict[str, str]] = []
        mappings: list[dict[str, Any]] = []
        missing_columns: list[str] = []
        resolved_fields: list[tuple[str, str | None]] = []
        for configured_field in mandatory_fields:
            actual = actual_by_normalized.get(
                CMDBParserService.normalize_header(configured_field)
            )
            resolved_fields.append((configured_field, actual))
            if actual is None:
                missing_columns.append(configured_field)
                mappings.append(
                    {
                        "configured_field": configured_field,
                        "cmdb_column": None,
                        "matched": False,
                        "match_type": "not_found",
                    }
                )
            else:
                matched.append(
                    {"configured_field": configured_field, "cmdb_column": actual}
                )
                mappings.append(
                    {
                        "configured_field": configured_field,
                        "cmdb_column": actual,
                        "matched": True,
                        "match_type": self._match_type(configured_field, actual),
                    }
                )

        populated_total = 0
        application_results: list[dict[str, Any]] = []
        for application in parsed.applications:
            missing_fields: list[str] = []
            for configured_field, actual_column in resolved_fields:
                value = (
                    application.source_data.get(actual_column)
                    if actual_column is not None
                    else None
                )
                if self._is_populated(value):
                    populated_total += 1
                else:
                    missing_fields.append(configured_field)
            populated_count = len(mandatory_fields) - len(missing_fields)
            completeness = self._percentage(populated_count, len(mandatory_fields))
            application_results.append(
                {
                    "internal_row_number": application.internal_row_number,
                    "application_key": application.application_key,
                    "application_code": (
                        str(application.source_data.get(parsed.application_code_column)).strip()
                        if parsed.application_code_column
                        and self._is_populated(
                            application.source_data.get(parsed.application_code_column)
                        )
                        else None
                    ),
                    "application_name": application.application_name,
                    "completeness_percentage": completeness,
                    "missing_mandatory_fields": missing_fields,
                    "evidence_type": self.evidence_type,
                    "source_of_truth_label": self.source_of_truth_label,
                    "reliability_label": self.reliability_label,
                    "missing_data_warnings": [
                        f"Missing mandatory field: {field}" for field in missing_fields
                    ],
                    "source_data": application.source_data,
                }
            )

        possible_total = parsed.row_count * len(mandatory_fields)
        overall_completeness = self._percentage(populated_total, possible_total)
        optional_inputs = optional_input_summary or {
            "confluence_available": False,
            "confluence_file_count": 0,
            "team_validation_available": False,
            "team_validation_upload_id": None,
            "cloudwatch_available": False,
            "cloudwatch_upload_id": None,
            "source_of_truth_inputs_used": ["cmdb"],
        }
        team_summary = team_validation_summary or {
            "team_validation_available": False,
            "upload_id": None,
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
        confluence_available = bool(optional_inputs.get("confluence_available"))
        team_available = bool(optional_inputs.get("team_validation_available"))
        if confluence_available and team_available:
            source_of_truth_label = "Source of Truth 3"
        elif confluence_available:
            source_of_truth_label = "Source of Truth 2"
        else:
            source_of_truth_label = "Source of Truth 1"
        reliability_label = (
            "High" if team_available and overall_completeness >= 70 else "Average"
        )
        if reliability_label == "High":
            reliability_reason = (
                "Team validation is available and mandatory completeness is at least 70%."
            )
        elif not team_available:
            reliability_reason = (
                "Team validation is unavailable; reliability is Average."
            )
        else:
            reliability_reason = (
                "Team validation is available, but mandatory completeness is below 70%; reliability is Average."
            )
        for application in application_results:
            application["source_of_truth_label"] = source_of_truth_label
            application["reliability_label"] = reliability_label
        duplicate_codes = self._duplicates(parsed, parsed.application_code_column)
        duplicate_names = self._duplicates(parsed, parsed.application_name_column)
        warnings: list[str] = []
        if missing_columns:
            warnings.append(
                "Configured mandatory columns are absent from the CMDB: "
                + ", ".join(missing_columns)
            )
        if duplicate_codes:
            warnings.append("Duplicate Application Code groups were detected")
        if duplicate_names:
            warnings.append("Duplicate application names were detected")
        if any(item["missing_mandatory_fields"] for item in application_results):
            warnings.append("One or more applications have missing mandatory field values")
        if parsed.row_count == 0:
            warnings.append("The CMDB worksheet contains no non-empty application rows")
        if team_available and not confluence_available:
            warnings.append(
                "Team Validation is available, but Source of Truth 3 requires both Confluence and Team Validation evidence."
            )
        if team_available:
            if team_summary.get("unmatched_team_validation_records", 0):
                warnings.append(
                    "One or more Team Validation records do not match a CMDB Application Code"
                )
            if team_summary.get(
                "cmdb_applications_missing_team_validation_record", 0
            ):
                warnings.append(
                    "One or more CMDB applications have no Team Validation record"
                )
            if team_summary.get("application_code_column") is None:
                warnings.append(
                    "Team Validation does not contain a recognized Application Code column"
                )
            elif team_summary.get("rows_missing_application_code", 0):
                warnings.append(
                    "One or more Team Validation rows have a missing Application Code"
                )
            if team_summary.get("invalid_yes_no_value_count", 0):
                warnings.append(
                    "Team Validation contains invalid values in a detected Yes/No column"
                )

        validation_status = "completed_with_warnings" if warnings else "validated"
        return {
            "upload_id": upload_id,
            "validation_status": validation_status,
            "summary": {
                "total_row_count": parsed.row_count,
                "total_column_count": parsed.column_count,
                "overall_completeness": overall_completeness,
                "matched_mandatory_columns": matched,
                "missing_mandatory_columns": missing_columns,
                "mandatory_field_mappings": mappings,
                "mandatory_fields_config_source": mandatory_fields_config_source,
                "mandatory_fields_config_upload_id": mandatory_fields_config_upload_id,
                "application_code_column": parsed.application_code_column,
                # Backward-compatible alias for clients using the earlier contract.
                "application_id_column": parsed.application_code_column,
                "duplicate_application_codes": duplicate_codes,
                "duplicate_application_ids": duplicate_codes,
                "duplicate_application_names": duplicate_names,
                "evidence_type": self.evidence_type,
                "source_of_truth_label": source_of_truth_label,
                "reliability_label": reliability_label,
                "reliability_reason": reliability_reason,
                # Retained for clients of the Phase A response contract.
                "reliability_note": reliability_reason,
                "team_validation_summary": team_summary,
                "optional_input_summary": optional_inputs,
                "missing_data_warnings": warnings,
            },
            "applications": application_results,
            "validation_warnings": warnings,
        }

    @staticmethod
    def _match_type(configured_field: str, actual_column: str) -> str:
        if configured_field == actual_column:
            return "exact"
        if configured_field.casefold() == actual_column.casefold():
            return "case_insensitive"
        return "normalized"

    @staticmethod
    def _is_populated(value: Any) -> bool:
        return value is not None and (not isinstance(value, str) or bool(value.strip()))

    @staticmethod
    def _percentage(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator * 100, 2)

    def _duplicates(
        self, parsed: ParsedCMDB, column: str | None
    ) -> list[dict[str, Any]]:
        if column is None:
            return []
        occurrences: dict[str, list[int]] = defaultdict(list)
        display_values: dict[str, str] = {}
        for application in parsed.applications:
            value = application.source_data.get(column)
            if not self._is_populated(value):
                continue
            display_value = str(value).strip()
            normalized_value = display_value.casefold()
            display_values.setdefault(normalized_value, display_value)
            occurrences[normalized_value].append(application.internal_row_number)
        return [
            {"value": display_values[value], "row_numbers": row_numbers}
            for value, row_numbers in occurrences.items()
            if len(row_numbers) > 1
        ]
