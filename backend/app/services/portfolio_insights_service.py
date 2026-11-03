from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.job_service import JobService
from app.services.result_helpers import bounded_limit, csv_text
from app.storage.base import StorageProvider


class PortfolioInsightsPrerequisiteError(ValueError):
    pass


class PortfolioInsightsResultNotFoundError(LookupError):
    pass


class PortfolioInsightsApplicationNotFoundError(LookupError):
    pass


class PortfolioInsightsService:
    """Combine current deterministic module artifacts without creating new evidence."""

    result_file_name = "portfolio_insights.json"
    max_stored_risks = 25_000
    max_stored_actions = 25_000
    unassigned_portfolio = "Unassigned"
    source_result_files = {
        "validation": "cmdb_validation.json",
        "dashboard": "dashboard_metrics.json",
        "similarity": "similarity.json",
        "technology": "technology.json",
        "output_families": "output_families.json",
    }
    field_aliases: dict[str, tuple[str, ...]] = {
        "portfolio": ("Portfolio", "Application Portfolio"),
        "business_criticality": (
            "Business Criticality",
            "Business criticality",
            "Criticality",
        ),
        "status": ("Status", "Application Status", "Lifecycle Status"),
        "operational_status": ("Operational Status", "Operational status"),
        "support_owner": ("Support Owner", "Application Support Owner"),
        "tech_product_owner": (
            "Tech Product Owner",
            "Technical Product Owner",
            "Technology Product Owner",
        ),
        "business_product_owner": (
            "Business Product Owner",
            "Product Owner",
        ),
    }
    missing_values = frozenset(
        {"", "-", "n/a", "na", "none", "null", "unknown", "blank", "not available", "tbd"}
    )
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    action_types = {
        "cmdb_missing_mandatory_data": "fix_cmdb_mandatory_field",
        "duplicate_application_code": "review_duplicate_application_code",
        "possible_duplicate_application": "review_possible_duplicate",
        "explicit_integration_with_unknown_target": "investigate_unknown_integration_target",
        "output_family_unmapped_application": "update_output_family_config",
        "output_family_config_member_not_found": "update_output_family_config",
        "output_family_ambiguous_member": "update_output_family_config",
        "output_family_without_members": "update_output_family_config",
        "missing_portfolio": "assign_portfolio",
        "missing_business_criticality": "assign_business_criticality",
    }

    def __init__(self, storage: StorageProvider, job_service: JobService) -> None:
        self.storage = storage
        self.job_service = job_service

    def run_analysis(
        self,
        job_id: str,
        *,
        risk_limit: int = 100,
        action_limit: int = 100,
        portfolio_limit: int = 100,
        include_low_severity: bool = True,
    ) -> dict[str, Any]:
        preview = self._load_current_preview(job_id)
        upload_id = str(preview["upload_id"])
        applications = self._prepare_applications(preview)
        source_results, module_status, warnings = self._load_source_results(
            job_id, upload_id, preview
        )

        risks = self._build_risks(applications, source_results)
        actions = self._build_actions(risks, applications)
        scorecards = self._build_scorecards(applications, source_results, risks)
        limitations = self._limitations(preview, source_results, module_status)
        for limitation in limitations:
            if limitation not in warnings:
                warnings.append(limitation)

        if len(risks) > self.max_stored_risks:
            warnings.append(
                f"Stored portfolio risks were limited to {self.max_stored_risks} records."
            )
        if len(actions) > self.max_stored_actions:
            warnings.append(
                f"Stored portfolio action items were limited to {self.max_stored_actions} records."
            )
        warnings = self._unique(warnings)

        validation = source_results.get("validation")
        dashboard = source_results.get("dashboard")
        source_label = self._first_value(
            validation, ("summary", "source_of_truth_label")
        ) or self._first_value(dashboard, ("overview", "source_of_truth_label"))
        reliability_label = self._first_value(
            validation, ("summary", "reliability_label")
        ) or self._first_value(dashboard, ("overview", "reliability_label"))
        # A current parsed CMDB is direct Source of Truth 1 evidence. The existing
        # analysis modules use Average when no validation enrichment is available.
        source_label = str(source_label or "Source of Truth 1")
        reliability_label = str(reliability_label or "Average")

        severity_counts = {
            severity: sum(risk["severity"] == severity for risk in risks)
            for severity in self.severity_order
        }
        executive_summary = self._executive_summary(
            applications,
            scorecards,
            risks,
            source_results,
            source_label,
            reliability_label,
            limitations,
        )
        missing_count = sum(
            item["status"] != "available" for item in module_status
        )
        summary = {
            "total_applications": len(applications),
            "total_portfolios": len(scorecards),
            "available_module_count": len(module_status) - missing_count,
            "missing_module_count": missing_count,
            "total_risk_count": len(risks),
            "critical_risk_count": severity_counts["critical"],
            "high_risk_count": severity_counts["high"],
            "medium_risk_count": severity_counts["medium"],
            "low_risk_count": severity_counts["low"],
            "action_item_count": len(actions),
            "source_of_truth_label": source_label,
            "reliability_label": reliability_label,
            "warning_count": len(warnings),
        }
        visible_risks = [
            risk
            for risk in risks
            if include_low_severity or risk["severity"] != "low"
        ]
        endpoints = self._endpoints(job_id)
        stored_result = {
            "status": "analyzed",
            "module_name": "portfolio_insights",
            "job_id": job_id,
            "upload_id": upload_id,
            "analysis_status": "completed_with_warnings" if warnings else "completed",
            "summary": summary,
            "executive_summary": executive_summary,
            "module_status": module_status,
            "top_portfolio_scorecards": scorecards[:portfolio_limit],
            "risk_sample": [self._public(risk) for risk in visible_risks[:risk_limit]],
            "action_item_sample": [self._public(item) for item in actions[:action_limit]],
            "warnings": warnings,
            "detail_endpoints": endpoints,
            # Bounded details support read APIs and exports without re-running sources.
            "portfolio_scorecards": scorecards,
            "risks": risks[: self.max_stored_risks],
            "actions": actions[: self.max_stored_actions],
            "stored_risk_count": min(len(risks), self.max_stored_risks),
            "stored_action_count": min(len(actions), self.max_stored_actions),
            "options": {
                "risk_limit": risk_limit,
                "action_limit": action_limit,
                "portfolio_limit": portfolio_limit,
                "include_low_severity": include_low_severity,
            },
        }
        self.storage.save_json(self._result_path(job_id), stored_result)
        return self._overview(stored_result)

    def get_summary(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return {
            key: result[key]
            for key in (
                "status",
                "module_name",
                "job_id",
                "upload_id",
                "analysis_status",
                "summary",
                "warnings",
            )
        }

    def get_executive_summary(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "analysis_status": result["analysis_status"],
            "executive_summary": result["executive_summary"],
            "warnings": result.get("warnings", []),
        }

    def get_module_status(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "modules": result.get("module_status", []),
            "warnings": result.get("warnings", []),
        }

    def get_portfolio_scorecard(self, job_id: str, limit: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 500)
        scorecards = result.get("portfolio_scorecards", [])
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "total_portfolio_count": len(scorecards),
            "portfolios": scorecards[:safe_limit],
        }

    def get_risks(
        self, job_id: str, limit: int, include_low_severity: bool
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 5_000)
        risks = [
            risk
            for risk in result.get("risks", [])
            if include_low_severity or risk.get("severity") != "low"
        ]
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "total_risk_count": len(risks),
            "risks": [self._public(risk) for risk in risks[:safe_limit]],
            "warnings": result.get("warnings", []),
        }

    def get_action_items(self, job_id: str, limit: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 5_000)
        actions = result.get("actions", [])
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "total_action_item_count": len(actions),
            "action_items": [self._public(item) for item in actions[:safe_limit]],
            "warnings": result.get("warnings", []),
        }

    def get_application_insight(
        self, job_id: str, application_code: str
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        preview = self._load_current_preview(job_id)
        applications = self._prepare_applications(preview)
        matches = [
            item
            for item in applications
            if item.get("application_code") == application_code
        ]
        if not matches:
            raise PortfolioInsightsApplicationNotFoundError(
                f"Application Code '{application_code}' was not found for job '{job_id}'"
            )
        application = matches[0]
        source_results, _, _ = self._load_source_results(
            job_id, str(preview["upload_id"]), preview
        )
        warnings: list[str] = []
        if len(matches) > 1:
            warnings.append(
                "Application Code matches multiple CMDB rows; the first matching row is shown."
            )

        validation_result = source_results.get("validation")
        validation_insights = None
        if validation_result is not None:
            records = [
                self._public(item)
                for item in validation_result.get("applications", [])
                if item.get("application_code") == application_code
            ]
            validation_insights = {"records": records}
        else:
            warnings.append("Validation insights are unavailable because validation results are missing.")

        similarity_result = source_results.get("similarity")
        similarity_insights = None
        if similarity_result is not None:
            similarity_insights = [
                pair
                for pair in similarity_result.get("top_similar_pairs", [])
                if application_code
                in (pair.get("application_code_a"), pair.get("application_code_b"))
            ]
        else:
            warnings.append("Similarity insights are unavailable because similarity results are missing.")

        technology_result = source_results.get("technology")
        technology_insights = None
        if technology_result is not None:
            technology_insights = {
                "obsolete_indicators": [
                    item
                    for item in technology_result.get("obsolete_indicators", [])
                    if item.get("application_code") == application_code
                ],
                "integrations": [
                    self._public(item)
                    for item in technology_result.get("integrations", [])
                    if application_code
                    in (
                        item.get("source_application_code"),
                        item.get("target_application_code"),
                    )
                ],
                "technology_clusters": [
                    self._public(cluster)
                    for cluster in technology_result.get("technology_clusters", [])
                    if any(
                        member.get("application_code") == application_code
                        for member in cluster.get("applications", [])
                    )
                ],
            }
        else:
            warnings.append("Technology insights are unavailable because technology results are missing.")

        output_result = source_results.get("output_families")
        output_insights = None
        if output_result is not None:
            output_insights = {
                "application_matrix": [
                    item
                    for item in output_result.get("application_matrix", [])
                    if item.get("application_code") == application_code
                ],
                "memberships": [
                    self._public(item)
                    for item in output_result.get("members", [])
                    if item.get("application_code") == application_code
                ],
                "gaps": [
                    item
                    for item in output_result.get("gaps", [])
                    if item.get("application_code") == application_code
                ],
            }
        else:
            warnings.append("Output-family insights are unavailable because output-family results are missing.")

        related_risks = [
            risk
            for risk in result.get("risks", [])
            if application_code in risk.get("_application_codes", [])
            or risk.get("application_code") == application_code
        ]
        risk_ids = {risk["risk_id"] for risk in related_risks}
        related_actions = [
            action
            for action in result.get("actions", [])
            if action.get("source_risk_id") in risk_ids
        ]
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "application": {
                key: application.get(key)
                for key in (
                    "application_code",
                    "application_name",
                    "portfolio",
                    "business_criticality",
                    "status",
                    "operational_status",
                    "support_owner",
                    "tech_product_owner",
                    "business_product_owner",
                )
            },
            "validation_insights": validation_insights,
            "similarity_insights": similarity_insights,
            "technology_insights": technology_insights,
            "output_family_insights": output_insights,
            "risks": [self._public(item) for item in related_risks],
            "action_items": [self._public(item) for item in related_actions],
            "warnings": self._unique(warnings),
        }

    def get_risks_csv(self, job_id: str) -> str:
        columns = [
            "risk_id", "risk_type", "severity", "application_code",
            "application_name", "portfolio", "evidence_module", "evidence",
            "recommended_action", "confidence",
        ]
        return self._csv(self._load_current_result(job_id).get("risks", []), columns)

    def get_action_items_csv(self, job_id: str) -> str:
        columns = [
            "action_id", "priority", "action_type", "application_code",
            "application_name", "portfolio", "description", "source_risk_id",
            "owner_hint", "evidence_module",
        ]
        return self._csv(self._load_current_result(job_id).get("actions", []), columns)

    def get_portfolio_scorecard_csv(self, job_id: str) -> str:
        columns = [
            "portfolio", "application_count", "completeness_percent",
            "critical_application_count", "high_business_criticality_count",
            "possible_duplicate_count", "obsolete_indicator_count",
            "explicit_integration_count", "unmapped_output_family_application_count",
            "risk_count", "highest_risk_severity", "warnings",
        ]
        return self._csv(
            self._load_current_result(job_id).get("portfolio_scorecards", []),
            columns,
            list_columns={"warnings"},
        )

    def _load_current_preview(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path):
            raise PortfolioInsightsPrerequisiteError(
                "Portfolio insights require a parsed CMDB preview for this job"
            )
        preview = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or preview.get("upload_id") != uploads[-1]:
            raise PortfolioInsightsPrerequisiteError(
                "Portfolio insights require the latest CMDB upload to be parsed"
            )
        records = preview.get("applications")
        if not isinstance(records, list) or preview.get("total_row_count") != len(records):
            raise PortfolioInsightsPrerequisiteError(
                "The parsed CMDB preview is invalid or incomplete; upload the CMDB again"
            )
        return preview

    def _load_current_result(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = self._result_path(job_id)
        if not self.storage.exists(path):
            raise PortfolioInsightsResultNotFoundError(
                f"Portfolio insights analysis has not been run for job '{job_id}'"
            )
        result = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or result.get("upload_id") != uploads[-1]:
            raise PortfolioInsightsResultNotFoundError(
                f"Portfolio insights analysis has not been run for the latest CMDB upload for job '{job_id}'"
            )
        return result

    def _load_source_results(
        self, job_id: str, upload_id: str, preview: dict[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
        results: dict[str, dict[str, Any]] = {}
        modules = [
            {
                "module_name": "cmdb_preview",
                "status": "available",
                "analysis_status": "parsed",
                "source_result_available": True,
                "key_metrics": {
                    "total_applications": preview.get("total_row_count", 0),
                    "total_columns": preview.get("total_column_count", 0),
                    "application_code_column": preview.get("application_code_column"),
                },
                "warnings": [],
            }
        ]
        warnings: list[str] = []
        job = self.job_service.require_job(job_id)
        for module_name, file_name in self.source_result_files.items():
            path = f"jobs/{job_id}/results/{file_name}"
            if not self.storage.exists(path):
                warning = (
                    f"{self._module_label(module_name)} results are missing; "
                    "related portfolio insight metrics are unavailable."
                )
                modules.append(self._missing_module(module_name, warning))
                warnings.append(warning)
                continue
            try:
                source = self.storage.load_json(path)
                is_current = source.get("upload_id") == upload_id
                if module_name == "output_families":
                    config_uploads = job.uploads.get(
                        UploadKind.OUTPUT_FAMILY_CONFIG.value, []
                    )
                    is_current = is_current and bool(config_uploads) and source.get(
                        "output_family_config_upload_id"
                    ) == config_uploads[-1]
                if not is_current:
                    warning = (
                        f"{self._module_label(module_name)} results do not match the latest inputs; "
                        "related portfolio insight metrics are unavailable."
                    )
                    modules.append(self._missing_module(module_name, warning))
                    warnings.append(warning)
                    continue
                if not isinstance(source, dict):
                    raise ValueError("stored result is not a JSON object")
                results[module_name] = source
                modules.append(
                    {
                        "module_name": module_name,
                        "status": "available",
                        "analysis_status": str(
                            source.get("analysis_status")
                            or source.get("validation_status")
                            or "completed"
                        ),
                        "source_result_available": True,
                        "key_metrics": self._module_metrics(module_name, source),
                        "warnings": self._source_warnings(module_name, source),
                    }
                )
            except Exception as error:  # Corrupt source artifacts should not abort Phase F.
                warning = (
                    f"{self._module_label(module_name)} results could not be read: {error}"
                )
                modules.append(
                    {
                        "module_name": module_name,
                        "status": "error",
                        "analysis_status": None,
                        "source_result_available": False,
                        "key_metrics": {},
                        "warnings": [warning],
                    }
                )
                warnings.append(warning)
        return results, modules, warnings

    def _prepare_applications(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        columns = preview.get("columns", [])
        resolved = self._resolve_columns(columns)
        code_column = preview.get("application_code_column") or preview.get(
            "application_id_column"
        )
        name_column = preview.get("application_name_column")
        applications: list[dict[str, Any]] = []
        for index, record in enumerate(preview.get("applications", [])):
            if not isinstance(record, dict):
                continue
            source = record.get("source_data", {})
            source = source if isinstance(source, dict) else {}
            code = self._text(source.get(code_column)) if code_column else None
            name = self._text(source.get(name_column)) if name_column else None
            fallback_name = self._text(record.get("application_name"))
            app = {
                "_index": index,
                "internal_row_number": record.get("internal_row_number", index + 1),
                "application_code": code,
                "application_name": name or fallback_name,
                "source_data": source,
            }
            for field, column in resolved.items():
                app[field] = self._text(source.get(column)) if column else None
            app["portfolio_key"] = app["portfolio"] or self.unassigned_portfolio
            app["owner_hint"] = (
                app["support_owner"]
                or app["tech_product_owner"]
                or app["business_product_owner"]
            )
            applications.append(app)
        return applications

    def _build_risks(
        self,
        applications: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        by_row = {item["internal_row_number"]: item for item in applications}
        by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for app in applications:
            if app.get("application_code"):
                by_code[str(app["application_code"])].append(app)

        validation = sources.get("validation")
        if validation:
            for record in validation.get("applications", []):
                missing = record.get("missing_mandatory_fields", [])
                if not missing:
                    continue
                app = by_row.get(record.get("internal_row_number"))
                risks.append(
                    self._risk(
                        "cmdb_missing_mandatory_data",
                        "medium",
                        app,
                        record.get("application_code"),
                        record.get("application_name"),
                        "validation",
                        "Missing mandatory CMDB fields: " + "; ".join(map(str, missing)),
                        "Populate or verify the listed mandatory CMDB fields.",
                        "high",
                    )
                )
            duplicate_groups = validation.get("summary", {}).get(
                "duplicate_application_codes",
                validation.get("summary", {}).get("duplicate_application_ids", []),
            )
            for group in duplicate_groups:
                code = self._text(group.get("value"))
                for row_number in group.get("row_numbers", []):
                    app = by_row.get(row_number)
                    severity = (
                        "critical"
                        if app and self._is_high_or_critical(app.get("business_criticality"))
                        else "high"
                    )
                    risks.append(
                        self._risk(
                            "duplicate_application_code",
                            severity,
                            app,
                            app.get("application_code") if app else code,
                            app.get("application_name") if app else None,
                            "validation",
                            f"Application Code '{code}' occurs on CMDB rows "
                            + ", ".join(map(str, group.get("row_numbers", []))),
                            "Review the duplicate Application Code rows and correct or confirm the identifier.",
                            "high",
                        )
                    )

        similarity = sources.get("similarity")
        if similarity:
            threshold = similarity.get("summary", {}).get(
                "possible_duplicate_threshold"
            )
            for pair in similarity.get("top_similar_pairs", []):
                score = pair.get("similarity_score")
                if not pair.get("possible_duplicate"):
                    continue
                if threshold is not None and (score is None or float(score) < float(threshold)):
                    continue
                code_a = self._text(pair.get("application_code_a"))
                code_b = self._text(pair.get("application_code_b"))
                app = by_code.get(code_a, [None])[0] if code_a else None
                evidence_parts = [f"Similarity score {score}"]
                if threshold is not None:
                    evidence_parts.append(f"duplicate threshold {threshold}")
                evidence_parts.append(
                    f"compared with Application Code '{code_b}'"
                    if code_b
                    else f"compared with '{pair.get('application_name_b')}'"
                )
                evidence = "; ".join(evidence_parts)
                risks.append(
                    self._risk(
                        "possible_duplicate_application",
                        "high",
                        app,
                        code_a,
                        pair.get("application_name_a"),
                        "similarity",
                        evidence,
                        "Review the scored application pair and confirm whether the records represent duplicates.",
                        "medium",
                        related_codes=[code for code in (code_a, code_b) if code],
                        related_portfolios=self._portfolios_for_codes(
                            by_code, (code_a, code_b)
                        ),
                    )
                )

        technology = sources.get("technology")
        if technology:
            for integration in technology.get("integrations", []):
                if integration.get("target_application_code") or integration.get(
                    "target_application_name"
                ):
                    continue
                code = self._text(integration.get("source_application_code"))
                app = by_code.get(code, [None])[0] if code else None
                risks.append(
                    self._risk(
                        "explicit_integration_with_unknown_target",
                        "medium",
                        app,
                        code,
                        integration.get("source_application_name"),
                        "technology",
                        f"{integration.get('evidence_field')}: {integration.get('evidence_value')}",
                        "Identify and record the target application for this explicit integration evidence.",
                        str(integration.get("confidence") or "low"),
                    )
                )

        output = sources.get("output_families")
        if output:
            for gap in output.get("gaps", []):
                mapping = {
                    "config_member_not_found_in_cmdb": (
                        "output_family_config_member_not_found",
                        "high",
                    ),
                    "ambiguous_name_match": (
                        "output_family_ambiguous_member",
                        "medium",
                    ),
                    "output_family_without_members": (
                        "output_family_without_members",
                        "low",
                    ),
                }.get(gap.get("gap_type"))
                if mapping is None:
                    continue
                risk_type, severity = mapping
                code = self._text(gap.get("application_code"))
                app = by_code.get(code, [None])[0] if code else None
                risks.append(
                    self._risk(
                        risk_type,
                        severity,
                        app,
                        code,
                        gap.get("application_name"),
                        "output_families",
                        str(gap.get("description") or "Output-family configuration gap."),
                        str(gap.get("recommended_action") or "Review the output-family configuration."),
                        "high",
                    )
                )
            if output.get("options", {}).get("include_unmapped"):
                for matrix in output.get("application_matrix", []):
                    if matrix.get("output_family_count") != 0:
                        continue
                    code = self._text(matrix.get("application_code"))
                    app = by_code.get(code, [None])[0] if code else None
                    risks.append(
                        self._risk(
                            "output_family_unmapped_application",
                            "low",
                            app,
                            code,
                            matrix.get("application_name"),
                            "output_families",
                            "Application has no explicit output-family assignment in the analyzed configuration.",
                            "Review the application and add an explicit output-family assignment when appropriate.",
                            "high",
                        )
                    )

        for app in applications:
            if self._is_missing(app.get("portfolio")):
                risks.append(
                    self._risk(
                        "missing_portfolio", "medium", app,
                        app.get("application_code"), app.get("application_name"),
                        "cmdb_preview", "CMDB Portfolio is blank or unavailable.",
                        "Assign or verify the Portfolio value in the CMDB.", "high",
                    )
                )
            if self._is_missing(app.get("business_criticality")):
                risks.append(
                    self._risk(
                        "missing_business_criticality", "medium", app,
                        app.get("application_code"), app.get("application_name"),
                        "cmdb_preview", "CMDB Business Criticality is blank or unavailable.",
                        "Assign or verify the Business Criticality value in the CMDB.", "high",
                    )
                )

        risks.sort(
            key=lambda item: (
                self.severity_order[item["severity"]],
                item["risk_type"],
                str(item.get("application_code") or "").casefold(),
                str(item.get("application_name") or "").casefold(),
                item["evidence"],
            )
        )
        for index, risk in enumerate(risks, start=1):
            risk["risk_id"] = f"RISK-{index:06d}"
        return risks

    def _build_actions(
        self, risks: list[dict[str, Any]], applications: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        owners_by_code = {
            item["application_code"]: item.get("owner_hint")
            for item in applications
            if item.get("application_code") and item.get("owner_hint")
        }
        actions: list[dict[str, Any]] = []
        for risk in risks:
            action_type = self.action_types.get(risk["risk_type"])
            if action_type is None:
                continue
            actions.append(
                {
                    "action_id": f"ACTION-{len(actions) + 1:06d}",
                    "priority": risk["severity"],
                    "action_type": action_type,
                    "application_code": risk.get("application_code"),
                    "application_name": risk.get("application_name"),
                    "portfolio": risk.get("portfolio"),
                    "description": risk["recommended_action"],
                    "source_risk_id": risk["risk_id"],
                    "owner_hint": risk.get("_owner_hint")
                    or owners_by_code.get(risk.get("application_code")),
                    "evidence_module": risk["evidence_module"],
                }
            )
        return actions

    def _build_scorecards(
        self,
        applications: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
        risks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for app in applications:
            grouped[str(app["portfolio_key"])].append(app)
        validation = sources.get("validation")
        similarity = sources.get("similarity")
        technology = sources.get("technology")
        output = sources.get("output_families")
        by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_row = {app["internal_row_number"]: app for app in applications}
        for app in applications:
            if app.get("application_code"):
                by_code[str(app["application_code"])].append(app)

        completeness: dict[str, list[float]] = defaultdict(list)
        if validation:
            for record in validation.get("applications", []):
                app = by_row.get(record.get("internal_row_number"))
                value = record.get("completeness_percentage")
                if app and isinstance(value, (int, float)):
                    completeness[app["portfolio_key"]].append(float(value))

        duplicate_counts: dict[str, int] = defaultdict(int)
        if similarity:
            for pair in similarity.get("top_similar_pairs", []):
                if not pair.get("possible_duplicate"):
                    continue
                keys = self._portfolios_for_codes(
                    by_code,
                    (
                        self._text(pair.get("application_code_a")),
                        self._text(pair.get("application_code_b")),
                    ),
                )
                for key in keys:
                    duplicate_counts[key] += 1

        obsolete_counts: dict[str, int] = defaultdict(int)
        integration_counts: dict[str, int] = defaultdict(int)
        if technology:
            for item in technology.get("obsolete_indicators", []):
                for app in by_code.get(str(item.get("application_code") or ""), []):
                    obsolete_counts[app["portfolio_key"]] += 1
                    break
            for item in technology.get("integrations", []):
                for app in by_code.get(
                    str(item.get("source_application_code") or ""), []
                ):
                    integration_counts[app["portfolio_key"]] += 1
                    break

        unmapped_counts: dict[str, int] = defaultdict(int)
        output_unmapped_available = bool(
            output and output.get("options", {}).get("include_unmapped")
        )
        if output_unmapped_available and output:
            for item in output.get("application_matrix", []):
                if item.get("output_family_count") != 0:
                    continue
                code = self._text(item.get("application_code"))
                if code and by_code.get(code):
                    unmapped_counts[by_code[code][0]["portfolio_key"]] += 1
                elif item.get("portfolio"):
                    unmapped_counts[str(item["portfolio"])] += 1
                else:
                    unmapped_counts[self.unassigned_portfolio] += 1

        risks_by_portfolio: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for risk in risks:
            keys = risk.get("_portfolio_keys", [])
            for key in set(keys):
                risks_by_portfolio[str(key)].append(risk)

        scorecards: list[dict[str, Any]] = []
        for portfolio, apps in grouped.items():
            warnings: list[str] = []
            if validation is None:
                warnings.append("Completeness is unavailable because validation results are missing.")
            if similarity is None:
                warnings.append("Possible duplicate count is unavailable because similarity results are missing.")
            if technology is None:
                warnings.append("Technology and integration counts are unavailable because technology results are missing.")
            if output is None:
                warnings.append("Unmapped output-family count is unavailable because output-family results are missing.")
            elif not output_unmapped_available:
                warnings.append("Unmapped output-family count is unavailable because include_unmapped was disabled.")
            portfolio_risks = risks_by_portfolio.get(portfolio, [])
            severities = [item["severity"] for item in portfolio_risks]
            scorecards.append(
                {
                    "portfolio": portfolio,
                    "application_count": len(apps),
                    "completeness_percent": (
                        round(sum(completeness[portfolio]) / len(completeness[portfolio]), 2)
                        if completeness.get(portfolio)
                        else None
                    ),
                    "critical_application_count": sum(
                        self._is_critical(app.get("business_criticality")) for app in apps
                    ),
                    "high_business_criticality_count": sum(
                        self._is_high(app.get("business_criticality")) for app in apps
                    ),
                    "possible_duplicate_count": (
                        duplicate_counts[portfolio] if similarity is not None else None
                    ),
                    "obsolete_indicator_count": (
                        obsolete_counts[portfolio] if technology is not None else None
                    ),
                    "explicit_integration_count": (
                        integration_counts[portfolio] if technology is not None else None
                    ),
                    "unmapped_output_family_application_count": (
                        unmapped_counts[portfolio]
                        if output_unmapped_available
                        else None
                    ),
                    "risk_count": len(portfolio_risks),
                    "highest_risk_severity": (
                        min(severities, key=self.severity_order.get)
                        if severities
                        else None
                    ),
                    "warnings": warnings,
                }
            )
        scorecards.sort(key=lambda item: (-item["application_count"], item["portfolio"].casefold()))
        return scorecards

    def _executive_summary(
        self,
        applications: list[dict[str, Any]],
        scorecards: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
        source_label: str,
        reliability_label: str,
        limitations: list[str],
    ) -> dict[str, Any]:
        validation = sources.get("validation")
        similarity = sources.get("similarity")
        technology = sources.get("technology")
        output = sources.get("output_families")
        severity_counts = {
            severity: sum(item["severity"] == severity for item in risks)
            for severity in self.severity_order
        }
        completeness = (
            validation.get("summary", {}).get("overall_completeness")
            if validation
            else None
        )
        possible_duplicates = (
            similarity.get("summary", {}).get("possible_duplicate_count")
            if similarity
            else None
        )
        obsolete_count = (
            technology.get("summary", {}).get("obsolete_indicator_count")
            if technology
            else None
        )
        integration_count = (
            technology.get("summary", {}).get("integration_count")
            if technology
            else None
        )
        output_warnings = (
            output.get("summary", {}).get("warning_count") if output else None
        )
        unmapped = (
            output.get("summary", {}).get("unmapped_cmdb_application_count")
            if output
            else None
        )
        findings = [
            f"The parsed CMDB contains {len(applications)} applications across {len(scorecards)} portfolio groups."
        ]
        if completeness is not None:
            findings.append(f"CMDB mandatory-field completeness is {completeness}%.")
        if possible_duplicates is not None:
            findings.append(
                f"Similarity analysis identified {possible_duplicates} possible duplicate application pairs."
            )
        if obsolete_count is not None:
            findings.append(
                f"Technology analysis identified {obsolete_count} potential obsolete technology indicators."
            )
        if integration_count is not None:
            findings.append(
                f"Technology analysis recorded {integration_count} explicit integration relationships."
            )
        if output_warnings is not None and unmapped is not None:
            findings.append(
                f"Output-family analysis reported {output_warnings} warnings and {unmapped} unmapped CMDB applications."
            )
        if risks:
            findings.append(
                "The deterministic risk register contains "
                f"{severity_counts['critical']} critical, {severity_counts['high']} high, "
                f"{severity_counts['medium']} medium, and {severity_counts['low']} low risks."
            )
        return {
            "total_applications": len(applications),
            "cmdb_completeness_percent": completeness,
            "source_of_truth_label": source_label,
            "reliability_label": reliability_label,
            "high_priority_risk_count": severity_counts["critical"] + severity_counts["high"],
            "medium_priority_risk_count": severity_counts["medium"],
            "low_priority_risk_count": severity_counts["low"],
            "possible_duplicate_count": possible_duplicates,
            "technology_obsolete_indicator_count": obsolete_count,
            "explicit_integration_count": integration_count,
            "output_family_warning_count": output_warnings,
            "unmapped_output_family_application_count": unmapped,
            "key_findings": findings,
            "limitations": limitations,
        }

    def _limitations(
        self,
        preview: dict[str, Any],
        sources: dict[str, dict[str, Any]],
        module_status: list[dict[str, Any]],
    ) -> list[str]:
        limitations = [
            f"{self._module_label(item['module_name'])} evidence is unavailable."
            for item in module_status
            if item["module_name"] != "cmdb_preview" and item["status"] != "available"
        ]
        technology = sources.get("technology")
        if technology and not technology.get("summary", {}).get(
            "explicit_integration_data_available"
        ):
            limitations.append(
                "Technology analysis contains no explicit integration relationships; integration findings are unavailable."
            )
        output = sources.get("output_families")
        if output and not output.get("options", {}).get("include_unmapped"):
            limitations.append(
                "Output-family analysis was run with include_unmapped disabled; application-level unmapped risks are unavailable."
            )
        if not preview.get("application_code_column"):
            limitations.append(
                "The CMDB has no Application Code column; exact Application Code application insights are unavailable."
            )
        return self._unique(limitations)

    def _risk(
        self,
        risk_type: str,
        severity: str,
        app: dict[str, Any] | None,
        application_code: Any,
        application_name: Any,
        evidence_module: str,
        evidence: str,
        recommended_action: str,
        confidence: str,
        *,
        related_codes: list[str] | None = None,
        related_portfolios: list[str] | None = None,
    ) -> dict[str, Any]:
        code = self._text(application_code)
        name = self._text(application_name)
        portfolio = app.get("portfolio") if app else None
        codes = related_codes or ([code] if code else [])
        portfolios = (
            related_portfolios
            if related_portfolios is not None
            else ([app["portfolio_key"]] if app else [])
        )
        return {
            "risk_id": "",
            "risk_type": risk_type,
            "severity": severity,
            "application_code": code,
            "application_name": name or (app.get("application_name") if app else None),
            "portfolio": portfolio,
            "evidence_module": evidence_module,
            "evidence": evidence,
            "recommended_action": recommended_action,
            "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
            "_application_codes": codes,
            "_portfolio_keys": portfolios,
            "_owner_hint": app.get("owner_hint") if app else None,
        }

    @classmethod
    def _module_metrics(cls, module_name: str, source: dict[str, Any]) -> dict[str, Any]:
        summary = source.get("summary", {})
        if module_name == "validation":
            return {
                "total_applications": summary.get("total_row_count"),
                "overall_completeness": summary.get("overall_completeness"),
                "duplicate_application_code_group_count": len(
                    summary.get("duplicate_application_codes", summary.get("duplicate_application_ids", []))
                ),
            }
        if module_name == "dashboard":
            overview = source.get("overview", {})
            return {
                "total_applications": overview.get("total_applications"),
                "overall_completeness": overview.get("overall_completeness"),
            }
        if module_name == "similarity":
            return {
                "similar_pair_count": summary.get("similar_pair_count"),
                "possible_duplicate_count": summary.get("possible_duplicate_count"),
            }
        if module_name == "technology":
            return {
                "technology_cluster_count": summary.get("technology_cluster_count"),
                "explicit_integration_count": summary.get("integration_count"),
                "obsolete_indicator_count": summary.get("obsolete_indicator_count"),
            }
        return {
            "total_families": summary.get("total_families_analyzed"),
            "unmapped_application_count": summary.get("unmapped_cmdb_application_count"),
            "warning_count": summary.get("warning_count"),
        }

    @staticmethod
    def _source_warnings(module_name: str, source: dict[str, Any]) -> list[str]:
        key = "validation_warnings" if module_name == "validation" else "warnings"
        values = source.get(key, [])
        return [str(item) for item in values] if isinstance(values, list) else []

    @staticmethod
    def _missing_module(module_name: str, warning: str) -> dict[str, Any]:
        return {
            "module_name": module_name,
            "status": "missing",
            "analysis_status": None,
            "source_result_available": False,
            "key_metrics": {},
            "warnings": [warning],
        }

    @classmethod
    def _resolve_columns(cls, columns: Iterable[Any]) -> dict[str, str | None]:
        by_normalized = {
            CMDBParserService.normalize_header(str(column)): str(column)
            for column in columns
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
    def _portfolios_for_codes(
        cls,
        by_code: dict[str, list[dict[str, Any]]],
        codes: Iterable[str | None],
    ) -> list[str]:
        portfolios: list[str] = []
        for code in codes:
            if not code:
                continue
            for app in by_code.get(code, []):
                key = str(app["portfolio_key"])
                if key not in portfolios:
                    portfolios.append(key)
        return portfolios

    @classmethod
    def _is_missing(cls, value: Any) -> bool:
        return value is None or str(value).strip().casefold() in cls.missing_values

    @staticmethod
    def _criticality(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @classmethod
    def _is_critical(cls, value: Any) -> bool:
        return cls._criticality(value) == "critical"

    @classmethod
    def _is_high(cls, value: Any) -> bool:
        return cls._criticality(value) == "high"

    @classmethod
    def _is_high_or_critical(cls, value: Any) -> bool:
        return cls._criticality(value) in {"high", "critical"}

    @staticmethod
    def _first_value(source: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
        value: Any = source
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if not key.startswith("_")}

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if str(value)))

    @staticmethod
    def _module_label(module_name: str) -> str:
        return {
            "cmdb_preview": "CMDB preview",
            "validation": "Validation",
            "dashboard": "Dashboard metrics",
            "similarity": "Similarity",
            "technology": "Technology",
            "output_families": "Output-family",
        }.get(module_name, module_name.replace("_", " ").title())

    @staticmethod
    def _csv(
        rows: list[dict[str, Any]],
        columns: list[str],
        list_columns: set[str] | None = None,
    ) -> str:
        return csv_text(rows, columns, list_columns=list_columns)

    @staticmethod
    def _endpoints(job_id: str) -> dict[str, str]:
        base = f"/api/jobs/{job_id}/analysis/portfolio-insights"
        return {
            "summary_endpoint": f"{base}/summary",
            "executive_summary_endpoint": f"{base}/executive-summary",
            "module_status_endpoint": f"{base}/module-status",
            "portfolio_scorecard_endpoint": f"{base}/portfolio-scorecard",
            "risks_endpoint": f"{base}/risks",
            "action_items_endpoint": f"{base}/action-items",
            "application_insight_endpoint_template": f"{base}/applications/{{application_code}}",
            "risks_csv_endpoint": f"{base}/risks.csv",
            "action_items_csv_endpoint": f"{base}/action-items.csv",
            "portfolio_scorecard_csv_endpoint": f"{base}/portfolio-scorecard.csv",
        }

    @staticmethod
    def _overview(result: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "status", "module_name", "job_id", "upload_id", "analysis_status",
            "summary", "executive_summary", "module_status",
            "top_portfolio_scorecards", "risk_sample", "action_item_sample",
            "warnings", "detail_endpoints",
        )
        return {key: result[key] for key in keys}

    def _result_path(self, job_id: str) -> str:
        return f"jobs/{job_id}/results/{self.result_file_name}"
