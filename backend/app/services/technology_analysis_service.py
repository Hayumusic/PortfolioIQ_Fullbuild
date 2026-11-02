from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, datetime
from io import StringIO
import re
from typing import Any, Iterable

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.job_service import JobService
from app.services.result_helpers import bounded_limit, csv_text
from app.storage.base import StorageProvider


class TechnologyAnalysisPrerequisiteError(ValueError):
    pass


class TechnologyAnalysisResultNotFoundError(LookupError):
    pass


class TechnologyAnalysisService:
    """Prepare complete, deterministic technology and explicit-integration views."""

    result_file_name = "technology.json"
    analysis_version = 4
    page_sizes = (25, 50, 100, 200)
    graph_edge_limit = 30
    no_integrations_warning = (
        "No explicit integration relationships were found in the uploaded CMDB."
    )
    placeholder_values = frozenset(
        {
            "",
            "-",
            "blank",
            "n a",
            "na",
            "no",
            "none",
            "not available",
            "not provided",
            "null",
            "tbd",
            "to be provided",
            "unavailable",
            "unknown",
            "yes",
        }
    )
    field_aliases: dict[str, tuple[str, ...]] = {
        "technology_stack": ("Technology Stack", "Tech Stack", "Technologies"),
        "application_technology": (
            "Application Technology",
            "Application Technologies",
        ),
        "platform": ("Platform",),
        "hosting_provider": ("Hosting Provider", "Cloud Provider"),
        "hosting_type": ("Hosting Type", "Hosting", "Hosting Model"),
        "database_technology": (
            "Database / Data Technology",
            "Database Technology",
            "Database",
            "Data Technology",
            "Data Store",
            "Datastore",
        ),
        "aka": (
            "AKA",
            "Also Known As",
            "Application Alias",
            "Application Aliases",
            "Aliases",
        ),
        "portfolio": ("Portfolio", "Application Portfolio"),
        "business_criticality": (
            "Business Criticality",
            "Business criticality",
            "Criticality",
        ),
        "description": ("Description", "Application Description", "App Description"),
        "application_age": ("Application Age", "App Age", "Age (Years)", "Age in Years"),
        "implementation_date": ("Implementation Date", "Implemented Date", "Launch Date"),
        "go_live_date": ("Go Live Date", "Go-Live Date", "Go Live", "Production Date"),
        "last_updated_date": ("Last Updated Date", "Application Updated Date", "Last Upgrade Date"),
        "technology_age": ("Technology Age", "Technology Age (Years)", "Technology Age in Years"),
        "technology_version": ("Technology Version", "Framework Version", "Platform Version"),
        "technology_updated_date": ("Technology Updated Date", "Technology Upgrade Date", "Technology Last Updated"),
        "api_webservices": (
            "API or Webservices",
            "API or Web Services",
            "API/Webservices",
            "APIs or Webservices",
            "APIs",
            "Webservices",
            "Web Services",
            "Interfaces",
            "Integrations",
        ),
    }
    technology_fields = (
        "technology_stack",
        "application_technology",
        "platform",
        "hosting_provider",
        "hosting_type",
        "database_technology",
    )
    integration_pattern = re.compile(
        r"\b(api|apis|web[ -]?services?|interfaces?|feeds?|integrat(?:e[sd]?|ion|ions|ing)|rest|soap|endpoints?|sftp|linked\s+server|database\s+link|batch|messages?|queues?|upstream|downstream|receives?|sends?|consumes?|publishes?|source\s+data|takes?)\b",
        re.IGNORECASE,
    )
    negative_integration_pattern = re.compile(
        r"\b(?:no|without)\s+(?:known\s+|documented\s+)?(?:api|apis|web[ -]?services?|interfaces?|feeds?|integrations?)\b",
        re.IGNORECASE,
    )
    integration_existence_pattern = re.compile(
        r"\b(?:connect(?:s|ed)?|consumes?|calls?|exposes?|provides?|uses?|integrat(?:e[sd]?|ing)|interfaces?|receives?|sends?|publishes?|flows?)\b",
        re.IGNORECASE,
    )
    integration_evidence_aliases = (
        "API or Webservices",
        "API or Web Services",
        "API/Webservices",
        "APIs or Webservices",
        "APIs",
        "Webservices",
        "Web Services",
        "Interfaces",
        "Integrations",
        "Integration Details",
        "Dependencies",
        "Dependency",
        "Upstream Applications",
        "Downstream Applications",
        "Data Flow",
        "Data Flows",
    )
    incoming_pattern = re.compile(
        r"\b(?:receives?(?:\s+data)?\s+from|takes?\s+(?:its\s+)?source\s+data\s+from|source\s+data\s+from|consumes?\s+(?:data\s+)?from)\b",
        re.IGNORECASE,
    )
    outgoing_pattern = re.compile(
        r"\b(?:sends?(?:\s+data)?\s+to|publishes?\s+to|data\s+flows?\s+to|(?:api|web[ -]?services?|interfaces?|feeds?|sftp)\b.{0,40}\bto)\b",
        re.IGNORECASE,
    )
    # Maintainable lifecycle rules. Each rule identifies a technology/version
    # that has a documented end-of-life concern; rules do not derive age from
    # an application name or an otherwise unversioned technology label.
    obsolete_patterns: tuple[tuple[str, re.Pattern[str], str], ...] = (
        ("vb6", re.compile(r"\bvb\s*6\b", re.IGNORECASE), "warning"),
        (
            "visual basic 6",
            re.compile(r"\bvisual\s+basic\s+6\b", re.IGNORECASE),
            "warning",
        ),
        ("classic asp", re.compile(r"\bclassic\s+asp\b", re.IGNORECASE), "warning"),
        ("asp classic", re.compile(r"\basp\s+classic\b", re.IGNORECASE), "warning"),
        ("silverlight", re.compile(r"\bsilverlight\b", re.IGNORECASE), "warning"),
        ("flash", re.compile(r"\bflash\b", re.IGNORECASE), "warning"),
        ("coldfusion", re.compile(r"\bcold\s*fusion\b", re.IGNORECASE), "warning"),
        ("lotus notes", re.compile(r"\blotus\s+notes\b", re.IGNORECASE), "warning"),
        (
            "access database",
            re.compile(r"\baccess\s+database\b", re.IGNORECASE),
            "warning",
        ),
        ("ms access", re.compile(r"\bms\s+access\b", re.IGNORECASE), "warning"),
        ("perl cgi", re.compile(r"\bperl\s+cgi\b", re.IGNORECASE), "warning"),
        (
            "windows server 2003",
            re.compile(r"\bwindows\s+server\s+2003\b", re.IGNORECASE),
            "critical",
        ),
        (
            "windows server 2008",
            re.compile(r"\bwindows\s+server\s+2008(?:\s*r2)?\b", re.IGNORECASE),
            "warning",
        ),
        (
            "internet explorer",
            re.compile(r"\binternet\s+explorer\b", re.IGNORECASE),
            "warning",
        ),
    )

    def __init__(self, storage: StorageProvider, job_service: JobService) -> None:
        self.storage = storage
        self.job_service = job_service

    def run_analysis(
        self,
        job_id: str,
        *,
        top_n: int = 10,
        cluster_limit: int = 50,
        integration_limit: int = 100,
        include_obsolete: bool = True,
    ) -> dict[str, Any]:
        # Retained for request compatibility; display limits never truncate analysis state.
        del cluster_limit, integration_limit
        preview = self._load_current_preview(job_id)
        upload_id = str(preview["upload_id"])
        resolved = self._resolve_columns(preview.get("columns", []))
        applications = [
            self._prepare_application(record, preview, resolved)
            for record in preview.get("applications", [])
            if isinstance(record, dict)
        ]

        all_clusters = self._build_clusters(applications)
        all_integrations = self._build_integrations(applications, resolved)
        all_obsolete_indicators = (
            self._build_obsolete_indicators(applications, resolved)
            if include_obsolete
            else []
        )
        integration_warnings = (
            [] if all_integrations else [self.no_integrations_warning]
        )
        obsolete_warnings = []
        if all_obsolete_indicators:
            obsolete_warnings.append(
                "Potential obsolete technology indicators require lifecycle and support-status confirmation."
            )
        warnings = self._analysis_warnings(
            job_id,
            upload_id,
            preview,
            resolved,
            include_obsolete,
        )
        for warning in (*integration_warnings, *obsolete_warnings):
            if warning not in warnings:
                warnings.append(warning)

        source_label, reliability_label = self._evidence_labels(job_id, upload_id)
        summary = {
            "total_applications_analyzed": len(applications),
            "technology_cluster_count": len(all_clusters),
            "integration_count": len(all_integrations),
            "explicit_integration_data_available": bool(all_integrations),
            "obsolete_indicator_count": len(all_obsolete_indicators),
            "source_of_truth_label": source_label,
            "reliability_label": reliability_label,
            "warning_count": len(warnings),
        }
        stored_applications = [self._stored_application(item) for item in applications]
        self._add_application_metrics(
            stored_applications, all_integrations, all_obsolete_indicators
        )
        portfolio_dependencies = self._build_portfolio_dependencies(
            stored_applications, all_integrations
        )
        integration_hubs = self._build_integration_hubs(
            stored_applications, all_integrations
        )
        endpoints = self._endpoints(job_id)
        result = {
            "status": "analyzed",
            "module_name": "technology",
            "job_id": job_id,
            "upload_id": upload_id,
            "analysis_status": "completed_with_warnings" if warnings else "completed",
            "analysis_version": self.analysis_version,
            "summary": summary,
            "top_technology_clusters": all_clusters[:top_n],
            "integration_summary": {
                "total_integration_count": len(all_integrations),
                "integration_data_available": bool(all_integrations),
                "integrations": [
                    self._public_integration(item)
                    for item in all_integrations[:top_n]
                ],
            },
            "obsolete_summary": {
                "obsolete_indicator_count": len(all_obsolete_indicators),
                "indicators": all_obsolete_indicators[:top_n],
            },
            "warnings": warnings,
            **endpoints,
            # Complete prepared artifacts. Read endpoints apply display pagination.
            "technology_clusters": all_clusters,
            "integrations": all_integrations,
            "obsolete_indicators": all_obsolete_indicators,
            "applications": stored_applications,
            "dimension_labels": {
                field: resolved[field]
                for field in self.technology_fields
                if resolved.get(field)
            },
            "integration_warnings": integration_warnings,
            "obsolete_warnings": obsolete_warnings,
            "portfolio_dependencies": portfolio_dependencies,
            "integration_hubs": integration_hubs,
            "include_obsolete": include_obsolete,
        }
        self.storage.save_json(self._result_path(job_id), result)
        return result

    def get_overview(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        public_keys = (
            "status",
            "module_name",
            "job_id",
            "upload_id",
            "analysis_status",
            "summary",
            "top_technology_clusters",
            "integration_summary",
            "obsolete_summary",
            "warnings",
            "summary_endpoint",
            "clusters_endpoint",
            "integrations_endpoint",
            "application_map_endpoint",
            "portfolio_map_endpoint",
            "obsolete_endpoint",
            "clusters_csv_endpoint",
            "integrations_csv_endpoint",
            "detail_endpoints",
        )
        return {key: result[key] for key in public_keys}

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

    def get_options(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        if "applications" not in result or "dimension_labels" not in result:
            raise TechnologyAnalysisResultNotFoundError(
                "Technology analysis must be rerun for the latest CMDB upload to prepare the visualization views"
            )
        applications = result.get("applications", [])
        integrations = result.get("integrations", [])
        indicators = result.get("obsolete_indicators", [])
        labels = result.get("dimension_labels", {})
        return {
            "dimensions": [
                {"key": key, "label": labels.get(key, key.replace("_", " ").title())}
                for key in self.technology_fields
                if key in labels
            ],
            "portfolios": sorted(
                {item["portfolio"] for item in applications if item.get("portfolio")},
                key=str.casefold,
            ),
            "business_criticalities": sorted(
                {
                    item["business_criticality"]
                    for item in applications
                    if item.get("business_criticality")
                },
                key=str.casefold,
            ),
            "applications": [
                {
                    "application_code": item.get("application_code"),
                    "application_name": item["application_name"],
                    "portfolio": item.get("portfolio"),
                }
                for item in applications
            ],
            "integration_types": sorted(
                {item["integration_type"] for item in integrations}, key=str.casefold
            ),
            "confidence_options": [
                value
                for value in ("high", "medium", "low")
                if any(item["confidence"] == value for item in integrations)
            ],
            "indicator_options": sorted(
                {item["indicator"] for item in indicators}, key=str.casefold
            ),
        }

    def get_inventory(
        self,
        job_id: str,
        search: str = "",
        portfolio: str = "",
        business_criticality: str = "",
        page: int = 1,
        page_size: int | str = 50,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        search_folded = search.strip().casefold()
        portfolio_folded = portfolio.strip().casefold()
        criticality_folded = business_criticality.strip().casefold()
        applications = [
            item
            for item in result.get("applications", [])
            if (
                not search_folded
                or search_folded in item["application_name"].casefold()
                or search_folded
                in (item.get("application_code") or "").casefold()
            )
            and (
                not portfolio_folded
                or (item.get("portfolio") or "").casefold() == portfolio_folded
            )
            and (
                not criticality_folded
                or (item.get("business_criticality") or "").casefold()
                == criticality_folded
            )
        ]
        applications.sort(
            key=lambda item: (
                (item.get("application_name") or "").casefold(),
                (item.get("application_code") or "").casefold(),
            )
        )
        sliced, safe_page, response_size = self._paginate(
            applications, page, page_size
        )
        return {
            "total_application_count": len(result.get("applications", [])),
            "filtered_application_count": len(applications),
            "page": safe_page,
            "page_size": response_size,
            "applications": [
                {key: value for key, value in item.items() if key != "technology_values"}
                for item in sliced
            ],
        }

    def get_landscape(
        self,
        job_id: str,
        dimension: str,
        portfolio: str,
        business_criticality: str,
        search: str,
        technology_value: str,
        page: int,
        page_size: int | str,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        labels = result.get("dimension_labels", {})
        if dimension not in labels:
            raise TechnologyAnalysisPrerequisiteError(
                "Select a technology dimension available in the current CMDB"
            )
        portfolio_folded = portfolio.strip().casefold()
        criticality_folded = business_criticality.strip().casefold()
        search_folded = search.strip().casefold()
        selected_folded = self._normalize_value(technology_value)

        def app_matches(item: dict[str, Any]) -> bool:
            if portfolio_folded and (item.get("portfolio") or "").casefold() != portfolio_folded:
                return False
            if criticality_folded and (item.get("business_criticality") or "").casefold() != criticality_folded:
                return False
            return not search_folded or search_folded in item["application_name"].casefold() or search_folded in (item.get("application_code") or "").casefold()

        applications = [item for item in result.get("applications", []) if app_matches(item)]
        grouped: dict[str, dict[str, Any]] = {}
        portfolio_grouped: dict[tuple[str, str], dict[str, Any]] = {}
        details: list[dict[str, Any]] = []
        for application in applications:
            seen: set[str] = set()
            for value in application.get("technology_values", {}).get(dimension, []):
                normalized = self._normalize_value(value)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                group = grouped.setdefault(normalized, {"label": value, "application_count": 0})
                group["application_count"] += 1
                portfolio_label = application.get("portfolio") or "Not Available"
                portfolio_key = (portfolio_label.casefold(), normalized)
                portfolio_item = portfolio_grouped.setdefault(
                    portfolio_key,
                    {
                        "portfolio": portfolio_label,
                        "technology_value": value,
                        "application_count": 0,
                    },
                )
                portfolio_item["application_count"] += 1
                if selected_folded and normalized == selected_folded:
                    details.append(
                        {
                            "application_name": application["application_name"],
                            "application_code": application.get("application_code"),
                            "portfolio": application.get("portfolio"),
                            "business_criticality": application.get("business_criticality"),
                            "technology_dimension": labels[dimension],
                            "technology_value": value,
                        }
                    )
        groupings = sorted(grouped.values(), key=lambda item: (-item["application_count"], item["label"].casefold()))
        details.sort(key=lambda item: ((item.get("application_code") or "").casefold(), item["application_name"].casefold()))
        paged_details, safe_page, response_size = self._paginate(
            details, page, page_size
        )
        return {
            "dimension": dimension,
            "dimension_label": labels[dimension],
            "groupings": groupings,
            "portfolio_groupings": sorted(
                portfolio_grouped.values(),
                key=lambda item: (
                    item["portfolio"].casefold(),
                    -item["application_count"],
                    item["technology_value"].casefold(),
                ),
            ),
            "selected_technology_value": technology_value or None,
            "total_application_count": len(details),
            "page": safe_page,
            "page_size": response_size,
            "applications": paged_details,
        }

    def get_integration_neighborhood(
        self,
        job_id: str,
        application_code: str,
        portfolio: str,
        integration_type: str,
        confidence: str,
        page: int,
        page_size: int | str,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        code_folded = application_code.strip().casefold()
        applications = result.get("applications", [])
        by_code = {
            (item.get("application_code") or "").casefold(): item
            for item in applications
            if item.get("application_code")
        }
        anchor = by_code.get(code_folded)
        if anchor is None:
            raise TechnologyAnalysisPrerequisiteError(
                "Select an application from the current CMDB"
            )
        portfolio_folded = portfolio.strip().casefold()
        type_folded = integration_type.strip().casefold()
        confidence_folded = confidence.strip().casefold()
        matches: list[dict[str, Any]] = []
        for item in result.get("integrations", []):
            source_code = (item.get("source_application_code") or "").casefold()
            target_code = (item.get("target_application_code") or "").casefold()
            if code_folded not in (source_code, target_code):
                continue
            if type_folded and item["integration_type"].casefold() != type_folded:
                continue
            if confidence_folded and item["confidence"].casefold() != confidence_folded:
                continue
            neighbor_code = target_code if source_code == code_folded else source_code
            neighbor = by_code.get(neighbor_code)
            endpoint_portfolios = {
                (endpoint.get("portfolio") or "").casefold()
                for endpoint in (anchor, neighbor)
                if endpoint is not None
            }
            if portfolio_folded and portfolio_folded not in endpoint_portfolios:
                continue
            public = self._public_integration(item)
            public["direction"] = (
                "unknown"
                if item.get("direction") == "unknown"
                else "outgoing"
                if source_code == code_folded
                else "incoming"
            )
            matches.append(public)
        paged_matches, safe_page, response_size = self._paginate(
            matches, page, page_size
        )
        known_for_graph = [item for item in matches if item.get("target_application_code")]
        nodes: dict[str, dict[str, Any]] = {
            code_folded: {
                "application_code": anchor.get("application_code"),
                "application_name": anchor["application_name"],
                "portfolio": anchor.get("portfolio"),
                "business_criticality": anchor.get("business_criticality"),
                "anchor": True,
            }
        }
        edges: list[dict[str, Any]] = []
        for item in known_for_graph[: self.graph_edge_limit]:
            source = by_code.get((item.get("source_application_code") or "").casefold())
            target = by_code.get((item.get("target_application_code") or "").casefold())
            if not source or not target:
                continue
            for node in (source, target):
                node_code = (node.get("application_code") or "").casefold()
                nodes[node_code] = {
                    "application_code": node.get("application_code"),
                    "application_name": node["application_name"],
                    "portfolio": node.get("portfolio"),
                    "business_criticality": node.get("business_criticality"),
                    "anchor": node_code == code_folded,
                }
            edges.append(
                {
                    "source_application_code": item["source_application_code"],
                    "target_application_code": item["target_application_code"],
                    "integration_type": item["integration_type"],
                    "confidence": item["confidence"],
                    "direction": item.get("direction", "unknown"),
                    "evidence_field": item["evidence_field"],
                }
            )
        return {
            "selected_application": nodes[code_folded],
            "total_integration_count": len(matches),
            "page": safe_page,
            "page_size": response_size,
            "integrations": paged_matches,
            "nodes": list(nodes.values()),
            "edges": edges,
            "graph_truncated": len(known_for_graph) > self.graph_edge_limit,
            "graph_edge_limit": self.graph_edge_limit,
            "portfolio_dependencies": result.get("portfolio_dependencies", []),
            "integration_hubs": result.get("integration_hubs", []),
        }

    def get_clusters(
        self, job_id: str, limit: int, portfolio: str = ""
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 500)
        portfolio_folded = portfolio.strip().casefold()
        scope_applications = [
            item
            for item in result.get("applications", [])
            if not portfolio_folded
            or (item.get("portfolio") or "").casefold() == portfolio_folded
        ]
        dimension_fields = {
            technology_type: CMDBParserService.normalize_header(field)
            for technology_type, field in result.get("dimension_labels", {}).items()
        }
        technology_version_fields = {
            CMDBParserService.normalize_header(alias)
            for alias in self.field_aliases["technology_version"]
        }
        indicators = result.get("obsolete_indicators", [])
        clusters: list[dict[str, Any]] = []
        for stored_cluster in result.get("technology_clusters", []):
            applications = [
                item
                for item in stored_cluster.get("applications", [])
                if not portfolio_folded
                or (item.get("portfolio") or "").casefold() == portfolio_folded
            ]
            if not applications:
                continue
            application_keys = {
                self._identity_key(
                    item.get("application_code"), item.get("application_name")
                )
                for item in applications
            }
            cluster_value = self._normalize_value(stored_cluster["label"])
            cluster_field = dimension_fields.get(stored_cluster["technology_type"])
            matching_indicators = [
                item
                for item in indicators
                if self._identity_key(
                    item.get("application_code"), item.get("application_name")
                )
                in application_keys
                and (
                    item.get("indicator") in {"application age", "technology age"}
                    or CMDBParserService.normalize_header(item.get("field", ""))
                    in technology_version_fields
                    or (
                        CMDBParserService.normalize_header(item.get("field", ""))
                        == cluster_field
                        and cluster_value in self._normalize_value(item.get("value", ""))
                    )
                )
            ]
            risky_keys = {
                self._identity_key(
                    item.get("application_code"), item.get("application_name")
                )
                for item in matching_indicators
            }
            if any(item.get("severity") == "critical" for item in matching_indicators):
                lifecycle_status = "Potential legacy technology concern"
            elif matching_indicators:
                lifecycle_status = "Potential legacy technology concern"
            else:
                lifecycle_status = "Not Available"
            shortcomings = sorted(
                {item["reason"] for item in matching_indicators}, key=str.casefold
            )
            clusters.append(
                {
                    **stored_cluster,
                    "application_count": len(applications),
                    "risky_application_count": len(risky_keys),
                    "lifecycle_status": lifecycle_status,
                    "shortcomings": shortcomings,
                    "concern_evidence": [
                        {
                            "application_code": item.get("application_code"),
                            "application_name": item["application_name"],
                            "source_field": item["field"],
                            "evidence_value": item["value"],
                            "reason": item["reason"],
                        }
                        for item in matching_indicators
                    ],
                    "applications": applications,
                    "cluster_reason": (
                        f"Grouped from direct values in {result.get('dimension_labels', {}).get(stored_cluster['technology_type'], stored_cluster['technology_type'].replace('_', ' ').title())}: "
                        f"{stored_cluster['label']}. Each application is counted once in this stack; applications may also belong to other stacks supported by their CMDB values."
                    ),
                }
            )
        clusters.sort(
            key=lambda item: (
                -item["application_count"],
                item["technology_type"],
                item["label"].casefold(),
            )
        )
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "portfolio": portfolio or None,
            "scope_application_count": len(scope_applications),
            "total_cluster_count": len(clusters),
            "clusters": clusters[:safe_limit],
            "warnings": [
                warning
                for warning in result.get("warnings", [])
                if "technology" in warning.casefold()
                or "application code" in warning.casefold()
            ],
        }

    def get_integrations(self, job_id: str, limit: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 1_000)
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "total_integration_count": result["summary"]["integration_count"],
            "integration_data_available": result["summary"][
                "explicit_integration_data_available"
            ],
            "integrations": [
                self._public_integration(item)
                for item in result.get("integrations", [])[:safe_limit]
            ],
            "warnings": result.get("integration_warnings", []),
        }

    def get_application_map(self, job_id: str, limit: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 1_000)
        preview = self._load_current_preview(job_id)
        resolved = self._resolve_columns(preview.get("columns", []))
        applications = [
            self._prepare_application(record, preview, resolved)
            for record in preview.get("applications", [])
            if isinstance(record, dict)
        ]
        by_identity = self._applications_by_identity(applications)
        integrations = result.get("integrations", [])[:safe_limit]
        included: set[int] = set()
        edges: list[dict[str, Any]] = []
        for integration in integrations:
            source_index = integration.get("_source_index")
            if isinstance(source_index, int):
                included.add(source_index)
            target_index = integration.get("_target_index")
            if not isinstance(target_index, int):
                continue
            included.add(target_index)
            edges.append(
                {
                    "source_application_code": integration.get(
                        "source_application_code"
                    ),
                    "target_application_code": integration.get(
                        "target_application_code"
                    ),
                    "integration_type": integration["integration_type"],
                    "confidence": integration["confidence"],
                    "evidence": (
                        f'{integration["evidence_field"]}: '
                        f'{integration["evidence_value"]}'
                    ),
                }
            )
        nodes = [self._map_node(applications[index]) for index in sorted(included)]
        # Compatibility for older stored results that do not carry row indexes.
        if integrations and not nodes:
            for integration in integrations:
                for code_key, name_key in (
                    ("source_application_code", "source_application_name"),
                    ("target_application_code", "target_application_name"),
                ):
                    application = by_identity.get(
                        self._identity_key(
                            integration.get(code_key), integration.get(name_key)
                        )
                    )
                    if application is not None:
                        nodes.append(self._map_node(application))
        map_warnings = list(result.get("integration_warnings", []))
        if integrations and not edges:
            map_warnings.append(
                "Explicit integration observations were found, but no target applications could be identified for graph edges."
            )
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "nodes": self._deduplicate_nodes(nodes),
            "edges": edges,
            "warnings": map_warnings,
        }

    def get_portfolio_map(self, job_id: str, limit: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 1_000)
        preview = self._load_current_preview(job_id)
        resolved = self._resolve_columns(preview.get("columns", []))
        applications = [
            self._prepare_application(record, preview, resolved)
            for record in preview.get("applications", [])
            if isinstance(record, dict)
        ]
        portfolio_counts = Counter(
            app["portfolio"] for app in applications if app.get("portfolio")
        )
        aggregates: dict[tuple[str, str], dict[str, Any]] = {}
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        for integration in result.get("integrations", [])[:safe_limit]:
            source_index = integration.get("_source_index")
            target_index = integration.get("_target_index")
            if not isinstance(source_index, int) or not isinstance(target_index, int):
                continue
            source_portfolio = applications[source_index].get("portfolio")
            target_portfolio = applications[target_index].get("portfolio")
            if not source_portfolio or not target_portfolio:
                continue
            key = (source_portfolio, target_portfolio)
            aggregate = aggregates.setdefault(
                key,
                {
                    "source_portfolio": source_portfolio,
                    "target_portfolio": target_portfolio,
                    "integration_count": 0,
                    "confidence": integration["confidence"],
                },
            )
            aggregate["integration_count"] += 1
            if confidence_rank[integration["confidence"]] < confidence_rank[aggregate["confidence"]]:
                aggregate["confidence"] = integration["confidence"]
        edges = sorted(
            aggregates.values(),
            key=lambda item: (
                -item["integration_count"],
                item["source_portfolio"].casefold(),
                item["target_portfolio"].casefold(),
            ),
        )[:safe_limit]
        map_warnings = list(result.get("integration_warnings", []))
        if result.get("integrations") and not edges:
            map_warnings.append(
                "No explicit application integrations with known source and target portfolios were available to aggregate."
            )
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "nodes": [
                {"portfolio": portfolio, "application_count": count}
                for portfolio, count in sorted(
                    portfolio_counts.items(), key=lambda item: item[0].casefold()
                )[:safe_limit]
            ],
            "edges": edges,
            "warnings": map_warnings,
        }

    def get_obsolete(
        self,
        job_id: str,
        portfolio: str = "",
        indicator: str = "",
        business_criticality: str = "",
        search: str = "",
        page: int = 1,
        page_size: int | str = 25,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        portfolio_folded = portfolio.strip().casefold()
        indicator_folded = indicator.strip().casefold()
        criticality_folded = business_criticality.strip().casefold()
        search_folded = search.strip().casefold()
        indicators = [
            item
            for item in result.get("obsolete_indicators", [])
            if (not portfolio_folded or (item.get("portfolio") or "").casefold() == portfolio_folded)
            and (not indicator_folded or item.get("indicator", "").casefold() == indicator_folded)
            and (
                not criticality_folded
                or (item.get("business_criticality") or "").casefold()
                == criticality_folded
            )
            and (
                not search_folded
                or search_folded in item["application_name"].casefold()
                or search_folded in (item.get("application_code") or "").casefold()
            )
        ]
        paged_indicators, safe_page, response_size = self._paginate(
            indicators, page, page_size
        )
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "obsolete_indicator_count": len(indicators),
            "page": safe_page,
            "page_size": response_size,
            "indicators": paged_indicators,
            "warnings": result.get("obsolete_warnings", []),
        }

    def get_clusters_csv(self, job_id: str) -> str:
        result = self._load_current_result(job_id)
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "cluster_key",
                "label",
                "technology_type",
                "application_count",
                "application_codes",
                "application_names",
            ]
        )
        for cluster in result.get("technology_clusters", []):
            applications = cluster.get("applications", [])
            writer.writerow(
                [
                    cluster["cluster_key"],
                    cluster["label"],
                    cluster["technology_type"],
                    cluster["application_count"],
                    "; ".join(
                        app["application_code"]
                        for app in applications
                        if app.get("application_code")
                    ),
                    "; ".join(app["application_name"] for app in applications),
                ]
            )
        return output.getvalue()

    def get_integrations_csv(self, job_id: str) -> str:
        result = self._load_current_result(job_id)
        columns = [
            "source_application_code",
            "source_application_name",
            "target_application_code",
            "target_application_name",
            "integration_type",
            "evidence_field",
            "evidence_value",
            "confidence",
            "warning",
        ]
        return csv_text(result.get("integrations", []), columns)

    def _load_current_preview(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path):
            raise TechnologyAnalysisPrerequisiteError(
                "Technology analysis requires a parsed CMDB preview for this job"
            )
        preview = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or preview.get("upload_id") != uploads[-1]:
            raise TechnologyAnalysisPrerequisiteError(
                "Technology analysis requires the latest CMDB upload to be parsed"
            )
        records = preview.get("applications")
        if not isinstance(records, list) or preview.get("total_row_count") != len(records):
            raise TechnologyAnalysisPrerequisiteError(
                "The parsed CMDB preview is invalid or incomplete; upload the CMDB again before running technology analysis"
            )
        return preview

    def _load_current_result(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = self._result_path(job_id)
        if not self.storage.exists(path):
            raise TechnologyAnalysisResultNotFoundError(
                f"Technology analysis has not been run for job '{job_id}'"
            )
        result = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or result.get("upload_id") != uploads[-1]:
            raise TechnologyAnalysisResultNotFoundError(
                f"Technology analysis has not been run for the latest CMDB upload for job '{job_id}'"
            )
        if result.get("analysis_version") != self.analysis_version:
            raise TechnologyAnalysisResultNotFoundError(
                "Technology analysis must be rerun for the latest visualization engine"
            )
        return result

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
    def _prepare_application(
        cls,
        record: dict[str, Any],
        preview: dict[str, Any],
        resolved: dict[str, str | None],
    ) -> dict[str, Any]:
        source = record.get("source_data", {})
        code_column = preview.get("application_code_column") or preview.get(
            "application_id_column"
        )
        name_column = preview.get("application_name_column")
        code = cls._display(source.get(code_column)) if code_column else ""
        source_name = cls._display(source.get(name_column)) if name_column else ""
        fallback_name = cls._display(record.get("application_name"))
        values = {
            field: cls._display(source.get(column)) if column else ""
            for field, column in resolved.items()
        }
        return {
            "row_index": int(record.get("internal_row_number", 0)) - 1,
            "application_code": code or None,
            "application_name": source_name or fallback_name or code or "Unnamed application",
            "portfolio": cls._optional_value(values["portfolio"]),
            "business_criticality": cls._optional_value(
                values["business_criticality"]
            ),
            "values": values,
            "source_data": {
                str(column): cls._display(value) for column, value in source.items()
            },
        }

    @classmethod
    def _build_clusters(cls, applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for application in applications:
            for technology_type in cls.technology_fields:
                seen: set[str] = set()
                for display_value in cls._technology_values(
                    application["values"].get(technology_type, "")
                ):
                    normalized = cls._normalize_value(display_value)
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    key = (technology_type, normalized)
                    cluster = grouped.setdefault(
                        key,
                        {
                            "cluster_key": f"{technology_type}:{cls._slug(normalized)}",
                            "technology_type": technology_type,
                            "display_values": Counter(),
                            "applications": [],
                            "rows": set(),
                        },
                    )
                    cluster["display_values"][display_value] += 1
                    application_key = cls._identity_key(
                        application.get("application_code"),
                        application.get("application_name"),
                    )
                    if application_key not in cluster["rows"]:
                        cluster["rows"].add(application_key)
                        cluster["applications"].append(
                            {
                                "application_code": application["application_code"],
                                "application_name": application["application_name"],
                                "portfolio": application["portfolio"],
                                "business_criticality": application[
                                    "business_criticality"
                                ],
                            }
                        )
        clusters = []
        for cluster in grouped.values():
            label = sorted(
                cluster["display_values"].items(),
                key=lambda item: (-item[1], item[0].casefold(), item[0]),
            )[0][0]
            applications_in_cluster = sorted(
                cluster["applications"],
                key=lambda item: (
                    (item["application_code"] or "").casefold(),
                    item["application_name"].casefold(),
                ),
            )
            clusters.append(
                {
                    "cluster_key": cluster["cluster_key"],
                    "label": label,
                    "technology_type": cluster["technology_type"],
                    "application_count": len(cluster["rows"]),
                    "applications": applications_in_cluster,
                    "warnings": [],
                }
            )
        clusters.sort(
            key=lambda item: (
                -item["application_count"],
                item["technology_type"],
                item["label"].casefold(),
            )
        )
        return clusters

    @classmethod
    def _build_integrations(
        cls,
        applications: list[dict[str, Any]],
        resolved: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        alias_targets, alias_kinds, alias_pattern = cls._build_alias_index(
            applications
        )
        evidence_fields = cls._integration_evidence_fields(applications, resolved)
        integrations: list[dict[str, Any]] = []
        # Link identity is independent of technology-stack membership. A repeated
        # source row or repeated evidence field must not create the same link twice.
        # Distinct endpoints, direction, or interface type remain distinct links.
        seen: set[tuple[str, str, str, str, str]] = set()
        for evidence_owner_index, evidence_owner in enumerate(applications):
            for column, field_is_integration_specific in evidence_fields:
                value = evidence_owner["source_data"].get(column, "").strip()
                if cls._is_placeholder(value):
                    continue
                clauses = cls._evidence_clauses(value)
                for clause in clauses:
                    if cls.negative_integration_pattern.search(clause):
                        continue
                    explicit_language = bool(cls.integration_pattern.search(clause))
                    target_matches = cls._find_targets_from_index(
                        clause,
                        evidence_owner_index,
                        alias_targets,
                        alias_kinds,
                        alias_pattern,
                    )
                    if not explicit_language and not (
                        field_is_integration_specific and target_matches
                    ):
                        continue
                    if (
                        explicit_language
                        and not field_is_integration_specific
                        and not target_matches
                        and not cls.integration_existence_pattern.search(clause)
                    ):
                        continue
                    integration_type = cls._integration_type(clause)
                    relation_direction = cls._relationship_direction(clause)
                    if target_matches:
                        for mentioned_index, match_kind in target_matches:
                            mentioned = applications[mentioned_index]
                            if relation_direction == "incoming":
                                source_index, target_index = (
                                    mentioned_index,
                                    evidence_owner_index,
                                )
                                source, target = mentioned, evidence_owner
                            else:
                                source_index, target_index = (
                                    evidence_owner_index,
                                    mentioned_index,
                                )
                                source, target = evidence_owner, mentioned
                            source_identity = cls._identity_key(
                                source.get("application_code"),
                                source.get("application_name"),
                            )
                            target_identity = cls._identity_key(
                                target.get("application_code"),
                                target.get("application_name"),
                            )
                            stable_direction = (
                                "unknown" if relation_direction == "unknown" else "directed"
                            )
                            key = (
                                source_identity,
                                target_identity,
                                stable_direction,
                                integration_type.casefold(),
                                CMDBParserService.normalize_header(column),
                            )
                            if key in seen:
                                continue
                            seen.add(key)
                            integrations.append(
                                {
                                    "source_application_code": source[
                                        "application_code"
                                    ],
                                    "source_application_name": source[
                                        "application_name"
                                    ],
                                    "target_application_code": target[
                                        "application_code"
                                    ],
                                    "target_application_name": target[
                                        "application_name"
                                    ],
                                    "direction": (
                                        "unknown"
                                        if relation_direction == "unknown"
                                        else "directed"
                                    ),
                                    "integration_type": integration_type,
                                    "evidence_field": column,
                                    "evidence_value": clause,
                                    "confidence": (
                                        "high" if match_kind == "code" else "medium"
                                    ),
                                    "warning": (
                                        "Direction is not established by the supporting CMDB evidence."
                                        if relation_direction == "unknown"
                                        else None
                                    ),
                                    "_source_index": source_index,
                                    "_target_index": target_index,
                                    "_evidence_owner_index": evidence_owner_index,
                                }
                            )
                    elif explicit_language:
                        key = (
                            cls._identity_key(
                                evidence_owner.get("application_code"),
                                evidence_owner.get("application_name"),
                            ),
                            "unidentified-target",
                            "unknown",
                            integration_type.casefold(),
                            cls._normalize_alias(clause),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        integrations.append(
                            {
                                "source_application_code": evidence_owner[
                                    "application_code"
                                ],
                                "source_application_name": evidence_owner[
                                    "application_name"
                                ],
                                "target_application_code": None,
                                "target_application_name": None,
                                "direction": "unknown",
                                "integration_type": integration_type,
                                "evidence_field": column,
                                "evidence_value": clause,
                                "confidence": "low",
                                "warning": (
                                    "Explicit integration evidence was found, but a target "
                                    "application could not be identified from the uploaded CMDB."
                                ),
                                "_source_index": evidence_owner_index,
                                "_target_index": None,
                                "_evidence_owner_index": evidence_owner_index,
                            }
                        )
        integrations.sort(
            key=lambda item: (
                (item["source_application_code"] or "").casefold(),
                item["source_application_name"].casefold(),
                (item["target_application_code"] or "").casefold(),
                (item["target_application_name"] or "").casefold(),
                item["evidence_field"].casefold(),
            )
        )
        return integrations

    @classmethod
    def _integration_evidence_fields(
        cls,
        applications: list[dict[str, Any]],
        resolved: dict[str, str | None],
    ) -> list[tuple[str, bool]]:
        available_columns = list(applications[0].get("source_data", {})) if applications else []
        integration_headers = {
            CMDBParserService.normalize_header(alias)
            for alias in cls.integration_evidence_aliases
        }
        fields = [
            (column, True)
            for column in available_columns
            if CMDBParserService.normalize_header(column) in integration_headers
        ]
        description = resolved.get("description")
        if description and all(column != description for column, _ in fields):
            fields.append((description, False))
        return fields

    @classmethod
    def _build_alias_index(
        cls,
        applications: list[dict[str, Any]],
    ) -> tuple[dict[str, int], dict[str, str], re.Pattern[str] | None]:
        candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for index, application in enumerate(applications):
            code = cls._normalize_alias(application.get("application_code"))
            if code:
                candidates[code].append((index, "code"))
            name = cls._display(application.get("application_name"))
            for alias in cls._name_aliases(name):
                candidates[alias].append((index, "name"))
            for alias in cls._technology_values(
                application.get("values", {}).get("aka", "")
            ):
                normalized = cls._normalize_alias(alias)
                if len(normalized) >= 2:
                    candidates[normalized].append((index, "aka"))
        targets: dict[str, int] = {}
        kinds: dict[str, str] = {}
        for alias, entries in candidates.items():
            indexes = {entry[0] for entry in entries}
            if len(indexes) != 1:
                continue
            targets[alias] = entries[0][0]
            kinds[alias] = "code" if any(kind == "code" for _, kind in entries) else entries[0][1]
        if not targets:
            return targets, kinds, None
        pattern = re.compile(
            r"(?<![a-z0-9])(?:"
            + "|".join(re.escape(alias) for alias in sorted(targets, key=len, reverse=True))
            + r")(?![a-z0-9])"
        )
        return targets, kinds, pattern

    @classmethod
    def _find_targets_from_index(
        cls,
        evidence: str,
        source_index: int,
        alias_targets: dict[str, int],
        alias_kinds: dict[str, str],
        alias_pattern: re.Pattern[str] | None,
    ) -> list[tuple[int, str]]:
        if alias_pattern is None:
            return []
        normalized = cls._normalize_alias(evidence)
        matches: dict[int, str] = {}
        for match in alias_pattern.finditer(normalized):
            alias = match.group(0)
            target_index = alias_targets[alias]
            if target_index == source_index:
                continue
            kind = alias_kinds[alias]
            if target_index not in matches or kind == "code":
                matches[target_index] = kind
        return sorted(matches.items())

    @classmethod
    def _name_aliases(cls, name: str) -> set[str]:
        aliases: set[str] = set()
        normalized_full = cls._normalize_alias(name)
        if len(normalized_full) >= 2:
            aliases.add(normalized_full)
        base = cls._normalize_alias(re.sub(r"\s*[\(\[].*?[\)\]]", " ", name))
        if len(base) >= 2:
            aliases.add(base)
        for value in re.findall(r"[\(\[]([^\)\]]+)[\)\]]", name):
            abbreviation = cls._normalize_alias(value)
            if 2 <= len(abbreviation) <= 20 and len(abbreviation.split()) <= 4:
                aliases.add(abbreviation)
        return aliases

    @classmethod
    def _evidence_clauses(cls, value: str) -> list[str]:
        clauses = [item.strip() for item in re.split(r"[\r\n.!;]+", value)]
        return [item for item in clauses if item and not cls._is_placeholder(item)]

    @classmethod
    def _relationship_direction(cls, value: str) -> str:
        if cls.incoming_pattern.search(value):
            return "incoming"
        if cls.outgoing_pattern.search(value):
            return "outgoing"
        return "unknown"

    @classmethod
    def _build_obsolete_indicators(
        cls,
        applications: list[dict[str, Any]],
        resolved: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        indicators: list[dict[str, Any]] = []
        for application in applications:
            age_indicator, age_available = cls._application_age_indicator(
                application, resolved
            )
            if age_indicator:
                indicators.append(age_indicator)
            if not age_available:
                technology_age_indicator = cls._technology_age_indicator(
                    application, resolved
                )
                if technology_age_indicator:
                    indicators.append(technology_age_indicator)
            for field in (*cls.technology_fields, "technology_version"):
                value = application["values"].get(field, "").strip()
                if cls._is_placeholder(value):
                    continue
                matched_patterns: set[str] = set()
                for label, pattern, severity in cls.obsolete_patterns:
                    if label in matched_patterns or not pattern.search(value):
                        continue
                    matched_patterns.add(label)
                    indicators.append(
                        {
                            "application_code": application["application_code"],
                            "application_name": application["application_name"],
                            "portfolio": application["portfolio"],
                            "business_criticality": application[
                                "business_criticality"
                            ],
                            "field": resolved.get(field) or field,
                            "value": value,
                            "indicator": label,
                            "reason": (
                                f"Potential legacy technology concern: the configured lifecycle rule "
                                f"for '{label}' matched this value in '{resolved.get(field) or field}'. "
                                "Review recommended."
                            ),
                            "severity": severity,
                        }
                    )
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        indicators.sort(
            key=lambda item: (
                severity_rank[item["severity"]],
                (item.get("portfolio") or "").casefold(),
                (item.get("application_code") or "").casefold(),
                item["application_name"].casefold(),
                item["indicator"].casefold(),
            )
        )
        return indicators

    @classmethod
    def _application_age_indicator(
        cls, application: dict[str, Any], resolved: dict[str, str | None]
    ) -> tuple[dict[str, Any] | None, bool]:
        current_year = date.today().year
        evidence: tuple[str, str, int] | None = None
        explicit_age = cls._age_years(application["values"].get("application_age", ""))
        if explicit_age is not None:
            evidence = (
                resolved.get("application_age") or "application_age",
                application["values"].get("application_age", ""),
                explicit_age,
            )
        else:
            for field in ("go_live_date", "implementation_date"):
                value = application["values"].get(field, "")
                evidence_year = cls._evidence_year(value)
                if evidence_year is not None:
                    evidence = (resolved.get(field) or field, value, current_year - evidence_year)
                    break
        if evidence is None:
            return None, False
        source_field, value, age = evidence
        latest_update = cls._evidence_year(
            application["values"].get("last_updated_date", "")
        )
        if age <= 12 or (latest_update is not None and current_year - latest_update <= 12):
            return None, True
        return cls._age_alert(
            application, source_field, value, "application age", age
        ), True

    @classmethod
    def _technology_age_indicator(
        cls, application: dict[str, Any], resolved: dict[str, str | None]
    ) -> dict[str, Any] | None:
        value = application["values"].get("technology_age", "")
        age = cls._age_years(value)
        if age is None or age <= 12:
            return None
        current_year = date.today().year
        latest_update = cls._evidence_year(
            application["values"].get("technology_updated_date", "")
        )
        if latest_update is not None and current_year - latest_update <= 12:
            return None
        return cls._age_alert(
            application,
            resolved.get("technology_age") or "technology_age",
            value,
            "technology age",
            age,
        )

    @staticmethod
    def _age_alert(
        application: dict[str, Any], source_field: str, value: str,
        indicator: str, age: int,
    ) -> dict[str, Any]:
        return {
            "application_code": application["application_code"],
            "application_name": application["application_name"],
            "portfolio": application["portfolio"],
            "business_criticality": application["business_criticality"],
            "field": source_field,
            "value": value,
            "indicator": indicator,
            "reason": (
                f"Potential legacy technology concern: '{source_field}' supports an age of "
                f"approximately {age} years and no later update within the last 12 years was found. "
                "Review recommended."
            ),
            "severity": "warning",
        }

    @classmethod
    def _age_years(cls, value: Any) -> int | None:
        if cls._is_placeholder(value):
            return None
        match = re.search(r"(?<!\d)(\d{1,3})(?:\.\d+)?(?:\s*(?:years?|yrs?))?(?!\d)", str(value))
        if not match:
            return None
        years = int(match.group(1))
        return years if 0 <= years <= 100 else None

    @classmethod
    def _evidence_year(cls, value: Any) -> int | None:
        if cls._is_placeholder(value):
            return None
        text = cls._display(value)
        year_match = re.search(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)", text)
        if year_match:
            return int(year_match.group(1))
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).year
            except ValueError:
                continue
        return None

    def _analysis_warnings(
        self,
        job_id: str,
        upload_id: str,
        preview: dict[str, Any],
        resolved: dict[str, str | None],
        include_obsolete: bool,
    ) -> list[str]:
        warnings: list[str] = []
        validation_path = f"jobs/{job_id}/results/cmdb_validation.json"
        validation_current = False
        if self.storage.exists(validation_path):
            validation_current = (
                self.storage.load_json(validation_path).get("upload_id") == upload_id
            )
        if not validation_current:
            warnings.append(
                "CMDB validation has not been run for the latest parsed upload; technology analysis used the parsed CMDB preview directly."
            )
        if not preview.get("application_code_column"):
            warnings.append(
                "Application Code was not found; response application code fields are null."
            )
        if not any(resolved.get(field) for field in self.technology_fields):
            warnings.append("No supported technology fields were found in the uploaded CMDB.")
        if not include_obsolete:
            warnings.append("Obsolete technology indicator checks were disabled for this run.")
        return warnings

    def _evidence_labels(self, job_id: str, upload_id: str) -> tuple[str, str]:
        path = f"jobs/{job_id}/results/cmdb_validation.json"
        if self.storage.exists(path):
            validation = self.storage.load_json(path)
            if validation.get("upload_id") == upload_id:
                summary = validation.get("summary", {})
                return (
                    summary.get("source_of_truth_label") or "Source of Truth 1",
                    summary.get("reliability_label") or "Average",
                )
        return "Source of Truth 1", "Average"

    @classmethod
    def _technology_values(cls, value: str) -> list[str]:
        if cls._is_placeholder(value):
            return []
        parts = re.split(r"\s*(?:[,;|]|\s/\s|\r?\n)\s*", value)
        return [part.strip() for part in parts if not cls._is_placeholder(part)]

    @classmethod
    def _is_placeholder(cls, value: Any) -> bool:
        normalized = " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))
        return normalized in cls.placeholder_values

    @classmethod
    def _optional_value(cls, value: str) -> str | None:
        return None if cls._is_placeholder(value) else value.strip() or None

    @staticmethod
    def _display(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _normalize_value(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9+#.]+", str(value).casefold()))

    @staticmethod
    def _normalize_alias(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "value"

    @classmethod
    def _integration_type(cls, value: str) -> str:
        normalized = cls._normalize_value(value)
        if re.search(r"\bsftp\b", normalized):
            return "sftp"
        if re.search(r"\blinked server\b", normalized):
            return "linked server"
        if re.search(r"\bdatabase link\b", normalized):
            return "database link"
        if re.search(r"\bfile feeds?\b", normalized):
            return "file feed"
        if re.search(r"\bbatch\b", normalized):
            return "batch"
        if re.search(r"\bmessages?\b|\bqueues?\b", normalized):
            return "message / queue"
        if re.search(r"\bweb services?\b|\bwebservices?\b", normalized):
            return "webservice"
        if re.search(r"\bapi(?:s)?\b|\brest\b|\bsoap\b|\bendpoint(?:s)?\b", normalized):
            return "api"
        if re.search(r"\binterface(?:s)?\b", normalized):
            return "interface"
        if re.search(r"\bfeed(?:s)?\b", normalized):
            return "feed"
        return "integration"

    @classmethod
    def _map_node(cls, application: dict[str, Any]) -> dict[str, Any]:
        technologies: list[str] = []
        for field in cls.technology_fields:
            for value in cls._technology_values(application["values"].get(field, "")):
                if value.casefold() not in {item.casefold() for item in technologies}:
                    technologies.append(value)
                if len(technologies) == 5:
                    break
            if len(technologies) == 5:
                break
        return {
            "application_code": application["application_code"],
            "application_name": application["application_name"],
            "portfolio": application["portfolio"],
            "technology_summary": "; ".join(technologies) or None,
        }

    @classmethod
    def _stored_application(cls, application: dict[str, Any]) -> dict[str, Any]:
        technology_values = {
            field: cls._technology_values(application["values"].get(field, ""))
            for field in cls.technology_fields
        }
        return {
            "application_code": application["application_code"],
            "application_name": application["application_name"],
            "portfolio": application["portfolio"],
            "business_criticality": application["business_criticality"],
            "hosting_type": cls._optional_value(
                application["values"].get("hosting_type", "")
            ),
            "hosting_provider": cls._optional_value(
                application["values"].get("hosting_provider", "")
            ),
            "technology_stack": cls._optional_value(
                application["values"].get("technology_stack", "")
            ),
            "database_technology": cls._optional_value(
                application["values"].get("database_technology", "")
            ),
            "technology_values": technology_values,
            "integration_count": 0,
            "incoming_integration_count": 0,
            "outgoing_related_integration_count": 0,
            "integration_types": [],
            "potential_legacy_indicator": False,
        }

    @classmethod
    def _add_application_metrics(
        cls,
        applications: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
    ) -> None:
        by_code = {
            (item.get("application_code") or "").casefold(): item
            for item in applications
            if item.get("application_code")
        }
        indicator_codes = {
            (item.get("application_code") or "").casefold()
            for item in indicators
            if item.get("application_code")
        }
        for application in applications:
            if (application.get("application_code") or "").casefold() in indicator_codes:
                application["potential_legacy_indicator"] = True
        for integration in integrations:
            source_code = (integration.get("source_application_code") or "").casefold()
            target_code = (integration.get("target_application_code") or "").casefold()
            source = by_code.get(source_code)
            target = by_code.get(target_code)
            if source:
                source["integration_count"] += 1
                source["outgoing_related_integration_count"] += 1
                if integration["integration_type"] not in source["integration_types"]:
                    source["integration_types"].append(integration["integration_type"])
            if target and target is not source:
                target["integration_count"] += 1
                if integration.get("direction") == "directed":
                    target["incoming_integration_count"] += 1
                else:
                    target["outgoing_related_integration_count"] += 1
                if integration["integration_type"] not in target["integration_types"]:
                    target["integration_types"].append(integration["integration_type"])
        for application in applications:
            application["integration_types"].sort(key=str.casefold)

    @classmethod
    def _build_portfolio_dependencies(
        cls,
        applications: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_code = {
            (item.get("application_code") or "").casefold(): item
            for item in applications
            if item.get("application_code")
        }
        counts: Counter[tuple[str, str]] = Counter()
        for integration in integrations:
            source = by_code.get(
                (integration.get("source_application_code") or "").casefold()
            )
            target = by_code.get(
                (integration.get("target_application_code") or "").casefold()
            )
            if not source or not target:
                continue
            source_portfolio = source.get("portfolio") or "Not Available"
            target_portfolio = target.get("portfolio") or "Not Available"
            counts[(source_portfolio, target_portfolio)] += 1
        return [
            {
                "source_portfolio": source,
                "target_portfolio": target,
                "integration_count": count,
            }
            for (source, target), count in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
            )
        ]

    @classmethod
    def _build_integration_hubs(
        cls,
        applications: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        neighbors: dict[str, set[str]] = defaultdict(set)
        incoming: Counter[str] = Counter()
        outgoing_related: Counter[str] = Counter()
        for integration in integrations:
            source = integration.get("source_application_code")
            target = integration.get("target_application_code")
            if not source:
                continue
            source_key = source.casefold()
            if target:
                target_key = target.casefold()
                neighbors[source_key].add(target_key)
                neighbors[target_key].add(source_key)
                if integration.get("direction") == "directed":
                    incoming[target_key] += 1
                    outgoing_related[source_key] += 1
                else:
                    outgoing_related[source_key] += 1
                    outgoing_related[target_key] += 1
            else:
                outgoing_related[source_key] += 1
        hubs = [
            {
                "application_name": item["application_name"],
                "application_code": item.get("application_code"),
                "portfolio": item.get("portfolio"),
                "business_criticality": item.get("business_criticality"),
                "total_connections": len(
                    neighbors.get((item.get("application_code") or "").casefold(), set())
                ),
                "incoming_connections": incoming[
                    (item.get("application_code") or "").casefold()
                ],
                "outgoing_related_connections": outgoing_related[
                    (item.get("application_code") or "").casefold()
                ],
            }
            for item in applications
            if item.get("application_code")
        ]
        hubs.sort(
            key=lambda item: (
                -item["total_connections"],
                -item["incoming_connections"],
                item["application_name"].casefold(),
            )
        )
        return hubs

    @classmethod
    def _page_size(cls, value: int) -> int:
        return value if value in cls.page_sizes else 25

    @classmethod
    def _paginate(
        cls, items: list[dict[str, Any]], page: int, page_size: int | str
    ) -> tuple[list[dict[str, Any]], int, int | str]:
        if str(page_size).casefold() == "all":
            return items, 1, "all"
        try:
            requested = int(page_size)
        except (TypeError, ValueError):
            requested = 25
        safe_size = cls._page_size(requested)
        safe_page = max(1, page)
        start = (safe_page - 1) * safe_size
        return items[start : start + safe_size], safe_page, safe_size

    @staticmethod
    def _identity_key(code: Any, name: Any) -> str:
        return f"code:{str(code).casefold()}" if code else f"name:{str(name).casefold()}"

    @classmethod
    def _applications_by_identity(
        cls, applications: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        return {
            cls._identity_key(app.get("application_code"), app["application_name"]): app
            for app in applications
        }

    @classmethod
    def _deduplicate_nodes(cls, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for node in nodes:
            unique.setdefault(
                cls._identity_key(node.get("application_code"), node["application_name"]),
                node,
            )
        return list(unique.values())

    @staticmethod
    def _endpoints(job_id: str) -> dict[str, Any]:
        base = f"/api/jobs/{job_id}/analysis/technology"
        return {
            "summary_endpoint": f"{base}/summary",
            "clusters_endpoint": f"{base}/clusters",
            "integrations_endpoint": f"{base}/integrations",
            "application_map_endpoint": f"{base}/application-map",
            "portfolio_map_endpoint": f"{base}/portfolio-map",
            "obsolete_endpoint": f"{base}/obsolete",
            "clusters_csv_endpoint": f"{base}/clusters.csv",
            "integrations_csv_endpoint": f"{base}/integrations.csv",
            "detail_endpoints": {
                "summary": f"{base}/summary",
                "clusters": f"{base}/clusters",
                "integrations": f"{base}/integrations",
                "application_map": f"{base}/application-map",
                "portfolio_map": f"{base}/portfolio-map",
                "obsolete": f"{base}/obsolete",
                "clusters_csv": f"{base}/clusters.csv",
                "integrations_csv": f"{base}/integrations.csv",
            },
        }

    def _result_path(self, job_id: str) -> str:
        return f"jobs/{job_id}/results/{self.result_file_name}"

    @staticmethod
    def _public_integration(integration: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in integration.items()
            if not key.startswith("_")
        }
