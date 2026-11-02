from __future__ import annotations

from collections import Counter
import re
from typing import Any, Iterable

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.job_service import JobService
from app.storage.base import StorageProvider


class DashboardMetricsPrerequisiteError(ValueError):
    pass


class DashboardMetricsResultNotFoundError(LookupError):
    pass


class DashboardMetricsService:
    """Build compact, deterministic dashboard metrics from stored job artifacts."""

    result_file_name = "dashboard_metrics.json"
    source_of_truth_label = "Source of Truth 1"
    reliability_label = "Average"

    field_aliases: dict[str, tuple[str, ...]] = {
        "status": ("Status", "Application Status"),
        "operational_status": ("Operational Status", "Operational status"),
        "portfolio": ("Portfolio", "Application Portfolio"),
        "business_criticality": (
            "Business Criticality",
            "Business criticality",
            "Criticality",
        ),
        "hosting_type": ("Hosting Type", "Hosting", "Hosting Model"),
        "hosting_provider": ("Hosting Provider", "Cloud Provider"),
        "technology_stack": ("Technology Stack", "Tech Stack", "Technologies"),
        "application_technology": (
            "Application Technology",
            "Application Technologies",
        ),
        "platform": ("Platform",),
        "user_authentication": (
            "User Authentication",
            "Authentication",
            "Authentication Type",
        ),
        "mfa": ("MFA", "Multi Factor Authentication", "Multifactor Authentication"),
        "waf": ("WAF", "Web Application Firewall"),
    }

    missing_values = frozenset(
        {
            "",
            "-",
            "n/a",
            "na",
            "none",
            "null",
            "unknown",
            "blank",
            "not available",
            "tbd",
        }
    )
    technology_stop_words = frozenset(
        {
            "a",
            "available",
            "be",
            "blank",
            "false",
            "n",
            "n/a",
            "na",
            "no",
            "none",
            "not",
            "null",
            "other",
            "provided",
            "tbd",
            "to",
            "true",
            "unknown",
            "yes",
        }
    )

    def __init__(self, storage: StorageProvider, job_service: JobService) -> None:
        self.storage = storage
        self.job_service = job_service

    def run_analysis(
        self,
        job_id: str,
        *,
        top_n: int = 10,
        include_similarity: bool = True,
    ) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        preview = self._load_current_preview(job_id, job.uploads)
        upload_id = str(preview["upload_id"])
        records = preview.get("applications")
        if not isinstance(records, list):
            raise DashboardMetricsPrerequisiteError(
                "The parsed CMDB preview is invalid"
            )
        if preview.get("total_row_count") != len(records):
            raise DashboardMetricsPrerequisiteError(
                "The parsed CMDB preview does not contain all normalized application records; upload the CMDB again before running dashboard metrics"
            )

        columns = preview.get("columns", [])
        if not isinstance(columns, list):
            raise DashboardMetricsPrerequisiteError(
                "The parsed CMDB preview is invalid"
            )
        resolved = self._resolve_columns(columns)
        sources = [
            record.get("source_data", {})
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("source_data", {}), dict)
        ]

        validation = self._load_optional_current_result(
            job_id, "cmdb_validation.json", upload_id
        )
        similarity = self._load_optional_current_result(
            job_id, "similarity.json", upload_id
        )
        warnings: list[str] = []
        if validation is None:
            warnings.append(
                "CMDB validation results are unavailable for the latest parsed upload; completeness and validation quality metrics are unavailable."
            )
        if similarity is None:
            warnings.append(
                "Similarity results are unavailable for the latest parsed upload; similarity and redundancy metrics are unavailable."
            )
        elif not include_similarity:
            warnings.append("Similarity metrics were excluded by request.")

        distributions = self._build_distributions(sources, resolved, top_n)
        data_quality = self._data_quality(validation)
        similarity_summary = self._similarity_summary(
            similarity if include_similarity else None, top_n
        )
        source_label = (
            validation.get("summary", {}).get("source_of_truth_label")
            if validation
            else None
        ) or self.source_of_truth_label
        reliability_label = (
            validation.get("summary", {}).get("reliability_label")
            if validation
            else None
        ) or self.reliability_label
        overview = {
            "total_applications": len(records),
            "total_columns": int(preview.get("total_column_count", len(columns))),
            "source_of_truth_label": source_label,
            "reliability_label": reliability_label,
            "overall_completeness": data_quality["overall_completeness"],
            "warning_count": len(warnings),
        }

        result = {
            "status": "analyzed",
            "module_name": "dashboard_metrics",
            "job_id": job_id,
            "upload_id": upload_id,
            "analysis_status": "completed_with_warnings" if warnings else "completed",
            "overview": overview,
            "cards": self._cards(
                overview, distributions, data_quality, similarity_summary
            ),
            "distributions": distributions,
            "data_quality": data_quality,
            "similarity_summary": similarity_summary,
            "warnings": warnings,
            "generated_from": {
                "cmdb_preview_available": True,
                "validation_result_available": validation is not None,
                "similarity_result_available": similarity is not None,
            },
            "summary_endpoint": f"/api/jobs/{job_id}/analysis/dashboard-metrics/summary",
        }
        self.storage.save_json(self._result_path(job_id), result)
        return result

    def get_summary(self, job_id: str) -> dict[str, Any]:
        return self._load_current_result(job_id)

    def _load_current_preview(
        self, job_id: str, uploads_by_kind: dict[str, list[str]]
    ) -> dict[str, Any]:
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path):
            raise DashboardMetricsPrerequisiteError(
                "Dashboard metrics require a parsed CMDB preview for this job"
            )
        preview = self.storage.load_json(path)
        uploads = uploads_by_kind.get(UploadKind.CMDB.value, [])
        if not uploads or preview.get("upload_id") != uploads[-1]:
            raise DashboardMetricsPrerequisiteError(
                "Dashboard metrics require the latest CMDB upload to be parsed"
            )
        return preview

    def _load_current_result(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = self._result_path(job_id)
        if not self.storage.exists(path):
            raise DashboardMetricsResultNotFoundError(
                f"Dashboard metrics have not been run for job '{job_id}'"
            )
        result = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or result.get("upload_id") != uploads[-1]:
            raise DashboardMetricsResultNotFoundError(
                f"Dashboard metrics have not been run for the latest CMDB upload for job '{job_id}'"
            )
        return result

    def _load_optional_current_result(
        self, job_id: str, file_name: str, upload_id: str
    ) -> dict[str, Any] | None:
        path = f"jobs/{job_id}/results/{file_name}"
        if not self.storage.exists(path):
            return None
        result = self.storage.load_json(path)
        return result if result.get("upload_id") == upload_id else None

    @classmethod
    def _resolve_columns(cls, columns: Iterable[Any]) -> dict[str, str | None]:
        text_columns = [str(column) for column in columns]
        by_normalized = {
            CMDBParserService.normalize_header(column): column for column in text_columns
        }
        return {
            field: next(
                (
                    by_normalized[CMDBParserService.normalize_header(alias)]
                    for alias in aliases
                    if CMDBParserService.normalize_header(alias) in by_normalized
                ),
                None,
            )
            for field, aliases in cls.field_aliases.items()
        }

    @classmethod
    def _build_distributions(
        cls,
        sources: list[dict[str, Any]],
        resolved: dict[str, str | None],
        top_n: int,
    ) -> dict[str, Any]:
        status_counts, _ = cls._categorical_counts(sources, resolved["status"])
        operational_counts, _ = cls._categorical_counts(
            sources, resolved["operational_status"]
        )
        portfolio_counts, missing_portfolio = cls._categorical_counts(
            sources, resolved["portfolio"]
        )
        criticality_counts, missing_criticality = cls._categorical_counts(
            sources, resolved["business_criticality"]
        )
        hosting_type_counts, missing_hosting_type = cls._categorical_counts(
            sources, resolved["hosting_type"]
        )
        hosting_provider_counts, missing_hosting_provider = cls._categorical_counts(
            sources, resolved["hosting_provider"]
        )
        authentication_counts, missing_authentication = cls._categorical_counts(
            sources, resolved["user_authentication"]
        )
        mfa_counts, missing_mfa = cls._categorical_counts(sources, resolved["mfa"])
        waf_counts, missing_waf = cls._categorical_counts(sources, resolved["waf"])

        technology_stack = cls._technology_counts(
            sources, resolved["technology_stack"], top_n
        )
        application_technology = cls._technology_counts(
            sources, resolved["application_technology"], top_n
        )
        platform_counts, _ = cls._categorical_counts(sources, resolved["platform"])
        missing_technology = sum(
            1
            for source in sources
            if all(
                cls._is_missing(source.get(resolved[field]))
                if resolved[field]
                else True
                for field in ("technology_stack", "application_technology", "platform")
            )
        )

        return {
            "application_status": {
                "status_counts": status_counts,
                "operational_status_counts": operational_counts,
            },
            "portfolio": {
                "counts": portfolio_counts,
                "top_portfolios": cls._top_items(portfolio_counts, top_n),
                "missing_portfolio_count": missing_portfolio,
            },
            "business_criticality": {
                "counts": criticality_counts,
                "missing_criticality_count": missing_criticality,
            },
            "hosting": {
                "hosting_type_counts": hosting_type_counts,
                "hosting_provider_counts": hosting_provider_counts,
                "missing_hosting_type_count": missing_hosting_type,
                "missing_hosting_provider_count": missing_hosting_provider,
            },
            "technology": {
                "top_technology_stack": technology_stack,
                "top_application_technology": application_technology,
                "top_platforms": cls._top_items(platform_counts, top_n),
                "missing_technology_count": missing_technology,
            },
            "security_access": {
                "user_authentication_counts": authentication_counts,
                "mfa_counts": mfa_counts,
                "waf_counts": waf_counts,
                "missing_user_authentication_count": missing_authentication,
                "missing_mfa_count": missing_mfa,
                "missing_waf_count": missing_waf,
            },
        }

    @classmethod
    def _categorical_counts(
        cls, sources: list[dict[str, Any]], column: str | None
    ) -> tuple[dict[str, int], int]:
        if column is None:
            return {}, len(sources)
        counts: Counter[str] = Counter()
        display_by_normalized: dict[str, str] = {}
        missing = 0
        for source in sources:
            value = source.get(column)
            if cls._is_missing(value):
                missing += 1
                continue
            display = str(value).strip()
            normalized = display.casefold()
            display_by_normalized.setdefault(normalized, display)
            counts[normalized] += 1
        ranked = sorted(
            counts,
            key=lambda item: (
                -counts[item],
                display_by_normalized[item].casefold(),
            ),
        )
        return {display_by_normalized[item]: counts[item] for item in ranked}, missing

    @classmethod
    def _technology_counts(
        cls, sources: list[dict[str, Any]], column: str | None, top_n: int
    ) -> list[dict[str, Any]]:
        if column is None:
            return []
        counts: Counter[str] = Counter()
        display_by_normalized: dict[str, str] = {}
        for source in sources:
            value = source.get(column)
            if cls._is_missing(value):
                continue
            tokens = re.findall(r"[\w][\w.+#-]*", str(value), flags=re.UNICODE)
            seen_in_application: set[str] = set()
            for token in tokens:
                normalized = token.casefold()
                if (
                    normalized in cls.technology_stop_words
                    or normalized in seen_in_application
                ):
                    continue
                seen_in_application.add(normalized)
                display_by_normalized.setdefault(normalized, token)
                counts[normalized] += 1
        ranked = sorted(
            counts,
            key=lambda item: (
                -counts[item],
                display_by_normalized[item].casefold(),
            ),
        )[:top_n]
        return [
            {"value": display_by_normalized[item], "count": counts[item]}
            for item in ranked
        ]

    @staticmethod
    def _top_items(counts: dict[str, int], top_n: int) -> list[dict[str, Any]]:
        return [
            {"value": value, "count": count}
            for value, count in list(counts.items())[:top_n]
        ]

    @staticmethod
    def _data_quality(validation: dict[str, Any] | None) -> dict[str, Any]:
        if validation is None:
            return {
                "overall_completeness": None,
                "matched_mandatory_columns": None,
                "missing_mandatory_columns": None,
                "duplicate_application_code_group_count": None,
                "duplicate_application_name_group_count": None,
                "warning_count": None,
            }
        summary = validation.get("summary", {})
        duplicate_codes = summary.get(
            "duplicate_application_codes", summary.get("duplicate_application_ids", [])
        )
        return {
            "overall_completeness": summary.get("overall_completeness"),
            "matched_mandatory_columns": summary.get("matched_mandatory_columns", []),
            "missing_mandatory_columns": summary.get("missing_mandatory_columns", []),
            "duplicate_application_code_group_count": len(duplicate_codes),
            "duplicate_application_name_group_count": len(
                summary.get("duplicate_application_names", [])
            ),
            "warning_count": len(validation.get("validation_warnings", [])),
        }

    @staticmethod
    def _similarity_summary(
        similarity: dict[str, Any] | None, top_n: int
    ) -> dict[str, Any]:
        if similarity is None:
            return {
                "similar_pair_count": None,
                "possible_duplicate_count": None,
                "similar_pair_threshold": None,
                "possible_duplicate_threshold": None,
                "top_possible_duplicates": [],
            }
        summary = similarity.get("summary", {})
        possible_duplicates = [
            pair
            for pair in similarity.get("top_similar_pairs", [])
            if isinstance(pair, dict) and pair.get("possible_duplicate") is True
        ][:top_n]
        return {
            "similar_pair_count": summary.get("similar_pair_count"),
            "possible_duplicate_count": summary.get("possible_duplicate_count"),
            "similar_pair_threshold": summary.get("similar_pair_threshold"),
            "possible_duplicate_threshold": summary.get("possible_duplicate_threshold"),
            "top_possible_duplicates": possible_duplicates,
        }

    @classmethod
    def _cards(
        cls,
        overview: dict[str, Any],
        distributions: dict[str, Any],
        data_quality: dict[str, Any],
        similarity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        top_portfolio = cls._first_value(distributions["portfolio"]["top_portfolios"])
        top_hosting = next(
            iter(distributions["hosting"]["hosting_type_counts"]), "Unavailable"
        )
        technology = distributions["technology"]
        top_technology = cls._first_value(technology["top_technology_stack"])
        if top_technology == "Unavailable":
            top_technology = cls._first_value(technology["top_application_technology"])
        if top_technology == "Unavailable":
            top_technology = cls._first_value(technology["top_platforms"])

        completeness = data_quality["overall_completeness"]
        missing_columns = data_quality["missing_mandatory_columns"]
        duplicate_codes = data_quality["duplicate_application_code_group_count"]
        similar_pairs = similarity["similar_pair_count"]
        possible_duplicates = similarity["possible_duplicate_count"]
        return [
            cls._card(
                "total_applications",
                "Total Applications",
                overview["total_applications"],
                "info",
                "Applications in the latest parsed CMDB upload.",
            ),
            cls._card(
                "cmdb_completeness",
                "CMDB Completeness",
                completeness if completeness is not None else "Unavailable",
                cls._completeness_severity(completeness),
                "Mandatory-field completeness from the latest validation result.",
            ),
            cls._card(
                "missing_mandatory_columns",
                "Missing Mandatory Columns",
                len(missing_columns)
                if missing_columns is not None
                else "Unavailable",
                cls._zero_severity(
                    None if missing_columns is None else len(missing_columns),
                    critical=True,
                ),
                "Configured mandatory columns absent from the CMDB.",
            ),
            cls._card(
                "duplicate_application_codes",
                "Duplicate Application Codes",
                duplicate_codes if duplicate_codes is not None else "Unavailable",
                cls._zero_severity(duplicate_codes),
                "Duplicate Application Code groups found by validation.",
            ),
            cls._card(
                "similar_application_pairs",
                "Similar Application Pairs",
                similar_pairs if similar_pairs is not None else "Unavailable",
                cls._zero_severity(similar_pairs),
                "Pairs meeting the stored similarity threshold.",
            ),
            cls._card(
                "possible_duplicates",
                "Possible Duplicates",
                possible_duplicates
                if possible_duplicates is not None
                else "Unavailable",
                cls._zero_severity(possible_duplicates, critical=True),
                "Pairs meeting the stored possible-duplicate threshold.",
            ),
            cls._card(
                "top_portfolio",
                "Top Portfolio",
                top_portfolio,
                "info",
                "Portfolio with the highest application count.",
            ),
            cls._card(
                "top_hosting_type",
                "Top Hosting Type",
                top_hosting,
                "info",
                "Most common populated hosting type.",
            ),
            cls._card(
                "top_technology",
                "Top Technology",
                top_technology,
                "info",
                "Most common meaningful technology or platform value.",
            ),
        ]

    @staticmethod
    def _card(
        key: str,
        label: str,
        value: Any,
        severity: str,
        description: str,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "value": value,
            "severity": severity,
            "description": description,
        }

    @staticmethod
    def _first_value(items: list[dict[str, Any]]) -> str:
        return str(items[0]["value"]) if items else "Unavailable"

    @staticmethod
    def _zero_severity(value: int | None, *, critical: bool = False) -> str:
        if value is None:
            return "warning"
        if value == 0:
            return "success"
        return "critical" if critical else "warning"

    @staticmethod
    def _completeness_severity(value: float | None) -> str:
        if value is None:
            return "warning"
        if value >= 90:
            return "success"
        if value >= 70:
            return "warning"
        return "critical"

    @classmethod
    def _is_missing(cls, value: Any) -> bool:
        return value is None or str(value).strip().casefold() in cls.missing_values

    def _result_path(self, job_id: str) -> str:
        return f"jobs/{job_id}/results/{self.result_file_name}"
