from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from openpyxl import Workbook
from typing import Any, Iterable

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.job_service import JobService
from app.services.result_helpers import bounded_limit, csv_text
from app.services.upload_config_service import UploadConfigService
from app.storage.base import StorageProvider


class OutputFamilyAnalysisPrerequisiteError(ValueError): pass
class OutputFamilyAnalysisResultNotFoundError(LookupError): pass
class OutputFamilyNotFoundError(LookupError): pass


class OutputFamilyAnalysisService:
    """MVP-compatible deterministic output-family classification."""

    result_file_name = "output_families.json"
    analysis_version = 4
    output_column_keywords = (
        "output", "report", "dashboard", "api", "export", "file", "feed",
        "extract", "dataset", "visualization", "visualisation", "analytics",
        "consumer", "downstream", "description", "business function",
    )
    output_indicators = (
        "report", "dashboard", "visualization", "visualisation", "api", "export",
        "file", "feed", "extract", "dataset", "data processing", "analytics",
        "interface", "download", "publication",
    )
    cluster_stop_words = frozenset({
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "into", "is", "it", "of", "on", "or", "our", "that", "the",
        "their", "this", "to", "via", "with", "application", "applications",
        "business", "data", "description", "function", "output", "outputs",
        "provide", "provides", "system", "used", "uses", "using", "not",
        "available", "none", "unknown", "yes", "no",
    })
    classification_statuses = ("Classified", "Multiple Families", "Insufficient Evidence")
    confidences = ("High", "Low")

    def __init__(self, storage: StorageProvider, job_service: JobService, upload_config_service: UploadConfigService) -> None:
        self.storage, self.job_service, self.upload_config_service = storage, job_service, upload_config_service

    async def run_analysis(self, job_id: str, *, family_limit: int = 50, member_limit: int = 200,
                           include_unmapped: bool = True, include_inactive: bool = True) -> dict[str, Any]:
        del include_unmapped, include_inactive
        preview, config = self._load_current_preview(job_id), self._load_config(job_id)
        taxonomy = self._taxonomy(config)
        applications = self._prepare_applications(preview)
        if not applications:
            raise OutputFamilyAnalysisPrerequisiteError("The current CMDB contains no applications to classify.")
        source_label, reliability_label = self._evidence_labels(job_id, str(preview["upload_id"]))
        matrix = [self._classify(app, taxonomy, source_label, reliability_label) for app in applications]
        self._assign_other_clusters(matrix)
        families, members = self._aggregate_families(taxonomy, matrix)
        gaps = self._classification_gaps(matrix)
        clusters = self._output_family_clusters(taxonomy, matrix, source_label, reliability_label)
        family_matrix = self._yes_no_matrix(taxonomy, matrix)
        alerts = self._redundancy_alerts(taxonomy, matrix, source_label, reliability_label)
        details = [item["output_details"] for item in matrix]
        exceptions = [{
            "application_name": item["application_name"],
            "output_description": item["output_summary"] or "Not Available",
            "reason": item["evidence_reason"], "confidence_level": item["confidence"],
            "evidence_type": item["evidence_type"],
            "missing_data_warnings": item["missing_data_warnings"],
        } for item in matrix if item["is_other"]]
        warnings = list(config.get("warnings", []))
        evidence_clustered_count = sum(self._is_evidence_clustered(item) for item in matrix)
        insufficient_evidence_count = sum(
            self._is_insufficient_output_evidence(item) for item in matrix
        )
        summary = {
            "total_families_analyzed": len(taxonomy), "total_application_count": len(matrix),
            "classified_application_count": len(matrix) - insufficient_evidence_count,
            "evidence_clustered_application_count": evidence_clustered_count,
            "applications_in_multiple_families": sum(len(item["configured_families"]) > 1 for item in matrix),
            "insufficient_evidence_application_count": insufficient_evidence_count,
            "unclassified_application_count": insufficient_evidence_count,
            "warning_count": len(gaps) + len(warnings), "source_of_truth_label": source_label,
            "reliability_label": reliability_label,
        }
        families.sort(key=lambda item: (-item["member_count"], item["family_name"].casefold()))
        members.sort(key=lambda item: (str(item.get("family_name") or "~").casefold(), item["application_name"].casefold()))
        result = {
            "status": "analyzed", "module_name": "output_families", "job_id": job_id,
            "upload_id": str(preview["upload_id"]), "output_family_config_upload_id": config.get("upload_id"),
            "analysis_status": "completed_with_warnings" if warnings else "completed",
            "analysis_version": self.analysis_version, "summary": summary,
            "top_output_families": families[:family_limit], "member_sample": members[:member_limit],
            "gap_sample": gaps[:member_limit], "warnings": warnings, **self._endpoints(job_id),
            "families": families, "members": members, "total_member_count": len(members), "gaps": gaps,
            "application_matrix": matrix, "output_family_clusters": clusters, "family_matrix": family_matrix,
            "redundancy_alerts": alerts, "output_details": details, "exceptions": exceptions,
            "classification_provider": "deterministic_direct_term_matching",
            "options": {"include_unmapped": True, "include_inactive": True},
        }
        self.storage.save_json(self._result_path(job_id), result)
        return self.get_overview(job_id)

    def _taxonomy(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        taxonomy, seen = [], set()
        for raw in config.get("families", []):
            if not isinstance(raw, dict): continue
            name, terms, identity_members = self._text(raw.get("name")), [], []
            key = self._normalize(name)
            if not name or not key or key in seen: continue
            seen.add(key); terms.append(name)
            terms.extend(self._text(value) for value in raw.get("keywords", []) if self._text(value))
            for member in raw.get("members", []):
                if isinstance(member, dict):
                    member_value = self._text(member.get("member_value"))
                    if member_value:
                        terms.append(member_value)
                    member_code = self._text(member.get("application_code"))
                    member_name = self._text(member.get("application_name"))
                    if member_code or member_name:
                        identity_members.append({
                            "application_code": self._normalize(member_code),
                            "application_name": self._normalize(member_name),
                            "display": member_name or member_code,
                        })
                elif self._text(member): terms.append(self._text(member))
            taxonomy.append({
                "name": name,
                "description": self._text(raw.get("description")),
                "terms": self._deduplicated_terms(terms),
                "identity_members": identity_members,
            })
        if not taxonomy:
            raise OutputFamilyAnalysisPrerequisiteError("A current-session Output Family taxonomy is required.")
        return taxonomy

    def _deduplicated_terms(self, values: Iterable[str]) -> list[dict[str, str]]:
        result, seen = [], set()
        for value in values:
            normalized = self._normalize(value)
            if normalized and normalized not in seen:
                seen.add(normalized); result.append({"display": str(value).strip(), "normalized": normalized})
        return result

    def _prepare_applications(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        code_column, name_column = preview.get("application_code_column"), preview.get("application_name_column")
        applications: list[dict[str, Any]] = []
        for index, raw in enumerate(preview.get("applications", [])):
            if not isinstance(raw, dict): continue
            source = raw.get("source_data") if isinstance(raw.get("source_data"), dict) else {}
            code = self._text(source.get(code_column)) if code_column else None
            name = (self._text(source.get(name_column)) if name_column else None) or self._text(raw.get("application_name")) or code or f"CMDB row {index + 1}"
            detected = self._detected_output_values(source)
            consumer_values = [value for header, value in detected if "consumer" in self._normalize(header) or "downstream" in self._normalize(header)]
            applications.append({
                "application_code": code, "application_key": code or f"record-{index + 1}", "application_name": name,
                "portfolio": self._field(source, ("Portfolio", "Application Portfolio")),
                "business_criticality": self._field(source, ("Business Criticality", "Criticality")),
                "detected_values": detected, "combined_text": " | ".join(value for _, value in detected),
                "consumers": " | ".join(consumer_values),
            })
        return applications

    def _detected_output_values(self, source: dict[str, Any]) -> list[tuple[str, str]]:
        result = []
        for header, raw_value in source.items():
            normalized_header = self._normalize(header)
            if any(
                self._contains_normalized_term(normalized_header, self._normalize(keyword))
                for keyword in self.output_column_keywords
            ):
                value = self._text(raw_value)
                if value: result.append((str(header), value))
        return result

    def _classify(self, application: dict[str, Any], taxonomy: list[dict[str, Any]],
                  source_label: str = "Current CMDB",
                  reliability_label: str = "Deterministic direct configured-term matching") -> dict[str, Any]:
        combined = application.get("combined_text", "")
        direct_text = self._normalize(combined)
        application_code = self._normalize(application.get("application_code"))
        application_name = self._normalize(application.get("application_name"))
        matches = []
        for family in taxonomy:
            family_evidence = [
                term["display"] for term in family["terms"]
                if self._contains_normalized_term(direct_text, term["normalized"])
            ]
            family_evidence.extend(
                member["display"] for member in family.get("identity_members", [])
                if (
                    member["application_code"]
                    and member["application_code"] == application_code
                ) or (
                    member["application_name"]
                    and member["application_name"] == application_name
                )
            )
            matches.append((family["name"], family_evidence))
        matches = [(family, terms) for family, terms in matches if terms]
        configured_families = [family for family, _ in matches]
        evidence_by_family = {
            self._normalize(family): self._ordered_unique(terms)
            for family, terms in matches
        }
        evidence = self._ordered_unique(term for _, terms in matches for term in terms)
        indicator = any(
            self._contains_normalized_term(direct_text, self._normalize(term))
            for term in self.output_indicators
        )
        if configured_families:
            output_families = configured_families
            assigned, confidence = "; ".join(configured_families), "High"
            evidence_reason = why = "Matched configured output family/member keywords"
            status = "Multiple Families" if len(configured_families) > 1 else "Classified"
        else:
            # Preserve the established empty configured-family collection for
            # downstream coverage metrics; assigned_output_family is the
            # canonical classifier result and the matrix maps it to Others.
            output_families = []
            assigned, confidence, status = "Others", "Low", "Insufficient Evidence"
            evidence_reason = "Output indicator found but no configured output family matched" if indicator else "No configured output family or output indicator matched"
            why = "Assigned to Others because no configured family clearly matched"
        exists = bool(combined)
        direct = "Directly found + rules-based classification" if exists else "Missing Evidence"
        evidence_type = "Direct CMDB Evidence + Inferred Analysis" if exists else "Missing Evidence"
        missing = "" if exists else "No output-related CMDB data found"
        fields = [header for header, _ in application.get("detected_values", [])]
        details = {
            "application_key": application["application_key"], "application_name": application["application_name"],
            "output_summary": combined, "output_family_classification": assigned,
            "key_evidence_or_keywords_found": " | ".join(evidence) if evidence else evidence_reason,
            "consumers_or_downstream_users": application.get("consumers", ""), "confidence_level": confidence,
            "why_classified": why, "direct_or_inferred": direct, "evidence_type": evidence_type,
            "missing_data_warnings": missing, "source_of_truth_label": source_label, "reliability_label": reliability_label,
        }
        return {
            "application_code": application.get("application_code"), "application_key": application["application_key"],
            "application_name": application["application_name"], "portfolio": application.get("portfolio"),
            "business_criticality": application.get("business_criticality"),
            "assignments": [
                {
                    "output_family": family,
                    "output_cluster": family,
                    "evidence": evidence_by_family.get(self._normalize(family), []),
                }
                for family in output_families
            ],
            "output_families": output_families, "configured_families": configured_families,
            "is_other": not configured_families,
            "output_clusters": output_families, "output_family_count": len(output_families),
            "assigned_output_family": assigned, "assigned_output_cluster": assigned, "confidence": confidence,
            "classification_status": status, "fields_used": fields, "matched_evidence": evidence,
            "classification_rationale": why, "warnings": [missing] if missing else [], "output_summary": combined,
            "evidence_reason": evidence_reason, "consumers": application.get("consumers", ""),
            "direct_or_inferred": direct, "evidence_type": evidence_type, "missing_data_warnings": missing,
            "detected_values": application.get("detected_values", []),
            "output_details": details,
        }

    def _assign_other_clusters(self, matrix: list[dict[str, Any]]) -> None:
        """Assign unmatched applications to evidence-derived, deterministic subclusters."""
        unmatched = [item for item in matrix if item["is_other"]]
        candidates_by_key: dict[str, dict[str, Any]] = {}
        application_candidates: dict[str, list[str]] = {}
        for item in unmatched:
            candidates: list[str] = []
            for _, value in item.get("detected_values", []):
                tokens = [
                    token for token in self._normalize(value).split()
                    if token not in self.cluster_stop_words
                    and (len(token) >= 3 or token in {"ai", "api", "bi"})
                    and not token.isdigit()
                ]
                for token in tokens:
                    candidate = candidates_by_key.setdefault(
                        token, {"display_values": {}, "application_keys": set()}
                    )
                    display = self._evidence_display_token(value, token)
                    candidate["display_values"][display] = candidate["display_values"].get(display, 0) + 1
                    candidate["application_keys"].add(item["application_key"])
                    if token not in candidates:
                        candidates.append(token)
            application_candidates[item["application_key"]] = candidates

        for item in unmatched:
            candidates = application_candidates.get(item["application_key"], [])
            supported_candidates = [
                token
                for token in candidates
                if len(candidates_by_key[token]["application_keys"]) >= 2
                or token in {self._normalize(value) for value in self.output_indicators}
            ]
            if supported_candidates:
                selected = sorted(
                    supported_candidates,
                    key=lambda token: (
                        -len(candidates_by_key[token]["application_keys"]),
                        -sum(candidates_by_key[token]["display_values"].values()),
                        token,
                    ),
                )[0]
                display_values = candidates_by_key[selected]["display_values"]
                evidence = sorted(
                    display_values,
                    key=lambda value: (-display_values[value], value.casefold(), value),
                )[0]
                cluster = f"Others / {self._concise_cluster_label(evidence)}"
                rationale = (
                    f"No configured family matched; grouped under Others using the CMDB evidence term '{evidence}'."
                )
                item["matched_evidence"] = self._ordered_unique(
                    [*item["matched_evidence"], evidence]
                )
                item["classification_status"] = "Classified"
            else:
                cluster = "Others / insufficient output evidence"
                rationale = (
                    "No configured family matched and the available output fields did not contain enough meaningful evidence to derive a subcluster."
                )
            item["assignments"] = [{
                "output_family": "Others",
                "output_cluster": cluster,
                "evidence": list(item["matched_evidence"]),
            }]
            item["output_clusters"] = [cluster]
            item["assigned_output_cluster"] = cluster
            item["classification_rationale"] = rationale
            item["output_details"]["output_family_classification"] = cluster
            item["output_details"]["why_classified"] = rationale
            if item["matched_evidence"]:
                item["output_details"]["key_evidence_or_keywords_found"] = " | ".join(item["matched_evidence"])

    @classmethod
    def _evidence_display_token(cls, value: str, normalized_token: str) -> str:
        for token in re.findall(r"[\w+#.]+", unicodedata.normalize("NFKC", value), flags=re.UNICODE):
            if cls._normalize(token) == normalized_token:
                return token
        return normalized_token

    @staticmethod
    def _concise_cluster_label(value: str) -> str:
        if value.isupper() and len(value) <= 5:
            return value
        return value[:1].upper() + value[1:]

    def _aggregate_families(self, taxonomy: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        families, members = [], []
        for position, definition in enumerate(taxonomy, 1):
            name = definition["name"]; matched = [item for item in matrix if self._same_family(name, item["configured_families"])]
            key = self._family_key(name, position)
            families.append({"family_key": key, "family_name": name, "family_description": definition["description"],
                             "member_count": len(matched), "portfolio_count": len({item["portfolio"] or "Not Available" for item in matched}),
                             "multiple_family_count": sum(len(item["configured_families"]) > 1 for item in matched), "warnings": []})
            for item in matched:
                members.append({"application_code": item["application_code"], "application_name": item["application_name"],
                    "portfolio": item["portfolio"], "family_key": key, "family_name": name, "output_cluster": name,
                    "confidence": item["confidence"], "classification_status": item["classification_status"],
                    "fields_used": item["fields_used"], "matched_evidence": item["matched_evidence"],
                    "classification_rationale": item["classification_rationale"], "warnings": item["warnings"]})
        return families, members

    def _output_family_clusters(self, taxonomy, matrix, source_label, reliability_label):
        result = []
        for family_name in [item["name"] for item in taxonomy] + ["Others"]:
            matched = [item for item in matrix if (item["is_other"] if family_name == "Others" else self._same_family(family_name, item["configured_families"]))]
            if matched:
                result.append({"output_family_name": family_name,
                    "applications_producing_this_output_family": " | ".join(item["application_name"] for item in matched),
                    "application_count": len(matched), "specific_outputs_identified": " | ".join(item["output_summary"] for item in matched if item["output_summary"]),
                    "similarity_notes": "Applications classified into the same output family using configured family/member list.",
                    "confidence_level": "Low" if family_name == "Others" else "High",
                    "evidence_type": "Direct CMDB Evidence + Inferred Analysis" if any(item["output_summary"] for item in matched) else "Missing Evidence",
                    "source_of_truth_labels_in_cluster": source_label, "reliability_labels_in_cluster": reliability_label})
        return result

    @classmethod
    def _yes_no_matrix(cls, taxonomy, matrix):
        configured_families = [item["name"] for item in taxonomy]
        other_clusters = sorted(
            {
                cluster
                for item in matrix if item.get("is_other", False)
                for cluster in item.get("output_clusters", [])
            },
            key=lambda value: (
                value == "Others / insufficient output evidence", value.casefold()
            ),
        )
        if not other_clusters:
            other_clusters = ["Others / insufficient output evidence"]
        families = configured_families + other_clusters
        rows_by_identity: dict[str, dict[str, Any]] = {}
        for item in matrix:
            identity = cls._normalize(item["application_key"])
            row = rows_by_identity.setdefault(
                identity,
                {
                    "application_key": item["application_key"],
                    "application_name": item["application_name"],
                    "values": {family: "No" for family in families},
                },
            )
            assigned = {
                cls._normalize(value)
                for value in (item.get("output_clusters", []) if item.get("is_other") else item["output_families"])
            }
            for family in families:
                if cls._normalize(family) in assigned:
                    row["values"][family] = "Yes"
        return {
            "output_families": families,
            "configured_families": configured_families,
            "other_clusters": other_clusters,
            "rows": list(rows_by_identity.values()),
        }

    @staticmethod
    def _redundancy_alerts(taxonomy, matrix, source_label, reliability_label):
        result = []
        for family in taxonomy:
            matched = [item for item in matrix if OutputFamilyAnalysisService._same_family(family["name"], item["configured_families"])]
            if len(matched) < 2: continue
            severity = "Low" if len(matched) == 2 else "Medium" if len(matched) == 3 else "High"
            result.append({"applications_involved": " | ".join(item["application_name"] for item in matched),
                "shared_output_family": family["name"], "similar_or_duplicated_outputs": " | ".join(item["output_summary"] for item in matched if item["output_summary"]),
                "business_impact": "Potential duplicated reporting, analytics, API, export, or data-processing capability.",
                "redundancy_severity": severity, "recommendation": "Review consumers, business process, dataset scope, and consolidation opportunity.",
                "evidence_type": "Direct CMDB Evidence + Inferred Analysis", "source_of_truth_label": source_label,
                "reliability_label": reliability_label})
        return result

    @staticmethod
    def _classification_gaps(matrix):
        return [{"gap_type": "unmatched_output_family", "severity": "warning", "family_key": None, "family_name": None,
                 "application_code": item["application_code"], "application_name": item["application_name"],
                 "description": item["evidence_reason"], "recommended_action": "Review the application output data and configured output-family members."}
                for item in matrix if item["is_other"]]

    def get_mvp_results(self, job_id):
        r = self._load_current_result(job_id)
        return {"output_family_clusters": r["output_family_clusters"], "family_matrix": r["family_matrix"],
                "redundancy_alerts": r["redundancy_alerts"], "output_details": r["output_details"], "exceptions": r["exceptions"],
                "downloads": {"details": r["detail_endpoints"]["details_csv"], "clusters": r["detail_endpoints"]["clusters_csv"], "alerts": r["detail_endpoints"]["alerts_csv"]}}

    def get_excel_export(self, job_id):
        result = self._load_current_result(job_id)
        workbook = Workbook()
        sheets = [
            ("Application Output Map", result["family_matrix"]["rows"]),
            ("Output Clusters", result["output_family_clusters"]),
            ("Output Details", result["output_details"]),
            ("Redundancy Alerts", result["redundancy_alerts"]),
        ]
        for index, (title, rows) in enumerate(sheets):
            sheet = workbook.active if index == 0 else workbook.create_sheet()
            sheet.title = title
            records = rows or []
            keys = list(records[0]) if records else []
            if title == "Application Output Map":
                keys = ["application_key", "application_name", *result["family_matrix"]["output_families"]]
            sheet.append(keys)
            for row in records:
                if title == "Application Output Map":
                    sheet.append([row.get("application_key"), row.get("application_name"), *[row.get("values", {}).get(family, "No") for family in result["family_matrix"]["output_families"]]])
                else:
                    sheet.append(["; ".join(value) if isinstance(value, list) else value for value in (row.get(key) for key in keys)])
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def get_overview(self, job_id):
        r = self._load_current_result(job_id); keys = ("status", "module_name", "job_id", "upload_id", "analysis_status", "summary", "top_output_families", "member_sample", "gap_sample", "warnings", "summary_endpoint", "families_endpoint", "members_endpoint", "gaps_endpoint", "application_matrix_endpoint", "families_csv_endpoint", "members_csv_endpoint", "gaps_csv_endpoint", "detail_endpoints")
        return {key: r[key] for key in keys}

    def get_summary(self, job_id):
        r = self._load_current_result(job_id); return {key: r[key] for key in ("status", "module_name", "job_id", "upload_id", "analysis_status", "summary", "warnings")}
    def get_families(self, job_id, limit):
        r = self._load_current_result(job_id); safe = bounded_limit(limit, 500); return {"job_id": job_id, "upload_id": r["upload_id"], "limit": safe, "total_family_count": len(r["families"]), "families": r["families"][:safe]}
    def get_family(self, job_id, family_key):
        r = self._load_current_result(job_id); family = next((x for x in r["families"] if x["family_key"] == family_key), None)
        if family is None: raise OutputFamilyNotFoundError(f"Output family '{family_key}' was not found")
        return {"job_id": job_id, "upload_id": r["upload_id"], "family": family, "members": [x for x in r["members"] if x["family_key"] == family_key]}
    def get_members(self, job_id, limit):
        r = self._load_current_result(job_id); safe = bounded_limit(limit, 5000); return {"job_id": job_id, "upload_id": r["upload_id"], "limit": safe, "total_member_count": len(r["members"]), "members": r["members"][:safe]}
    def get_gaps(self, job_id):
        r = self._load_current_result(job_id); return {"job_id": job_id, "upload_id": r["upload_id"], "warning_count": r["summary"]["warning_count"], "gaps": r["gaps"], "warnings": r["warnings"]}
    def get_application_matrix(self, job_id, limit):
        r = self._load_current_result(job_id); safe = bounded_limit(limit, 5000); return {"job_id": job_id, "upload_id": r["upload_id"], "limit": safe, "total_application_count": len(r["application_matrix"]), "applications": [self._public_application(x) for x in r["application_matrix"][:safe]]}

    def get_analysis_view(self, job_id, **_):
        r = self._load_current_result(job_id)
        return {"options": self._filter_options(r), "filtered_application_count": len(r["application_matrix"]),
                "insufficient_evidence_application_count": sum(self._is_insufficient_output_evidence(x) for x in r["application_matrix"]), "multiple_family_application_count": sum(len(x["configured_families"]) > 1 for x in r["application_matrix"]),
                "families": [{"output_family": x["output_family_name"], "application_count": x["application_count"], "portfolio_count": 0, "multiple_family_count": 0} for x in r["output_family_clusters"]], "coverage": [],
                "potential_overlaps": [{"output_family": x["shared_output_family"], "number_of_applications": len(x["applications_involved"].split(" | ")), "number_of_portfolios": 0, "potential_overlap": True} for x in r["redundancy_alerts"]]}

    def get_application_mapping(self, job_id, *, portfolio="", output_family="", confidence="", classification_status="", search="", display_size="50"):
        r = self._load_current_result(job_id); rows = self._filter_applications(r["application_matrix"], portfolio=portfolio, output_family=output_family, confidence=confidence, classification_status=classification_status, search=search)
        rows.sort(key=lambda x: (x["application_name"].casefold(), str(x["application_code"] or "").casefold())); shown = rows if display_size == "all" else rows[:int(display_size)]
        return {"options": self._filter_options(r), "display_size": display_size, "total_application_count": len(rows), "returned_application_count": len(shown), "insufficient_evidence_application_count": sum(self._is_insufficient_output_evidence(x) for x in rows), "multiple_family_application_count": sum(len(x["configured_families"]) > 1 for x in rows), "applications": [self._public_application(x) for x in shown]}

    @staticmethod
    def _public_application(item):
        keys = ("application_code", "application_name", "portfolio", "business_criticality", "assignments", "output_families", "output_clusters", "output_family_count", "assigned_output_family", "assigned_output_cluster", "confidence", "classification_status", "fields_used", "matched_evidence", "classification_rationale", "warnings")
        return {key: item[key] for key in keys}

    def _filter_applications(self, applications, *, portfolio="", output_family="", confidence="", classification_status="", search=""):
        p, f, c, s, q = map(self._normalize, (portfolio, output_family, confidence, classification_status, search))
        return [x for x in applications if (not p or self._normalize(x.get("portfolio")) == p) and (not f or self._normalize(x["assigned_output_family"]) == f or f in {self._normalize(v) for v in [*x["output_families"], *x["output_clusters"]]}) and (not c or self._normalize(x["confidence"]) == c) and (not s or self._normalize(x["classification_status"]) == s) and (not q or q in self._normalize(f"{x['application_name']} {x.get('application_code') or ''}"))]
    def _filter_options(self, r):
        return {"portfolios": sorted({x["portfolio"] for x in r["application_matrix"] if x.get("portfolio")}, key=str.casefold), "output_families": r["family_matrix"]["output_families"], "confidences": list(self.confidences), "classification_statuses": list(self.classification_statuses)}

    @classmethod
    def _same_family(cls, family: str, assigned: Iterable[str]) -> bool:
        normalized = cls._normalize(family)
        return normalized in {cls._normalize(value) for value in assigned}

    @classmethod
    def _is_insufficient_output_evidence(cls, item: dict[str, Any]) -> bool:
        return cls._same_family(
            "Others / insufficient output evidence", item.get("output_clusters", [])
        )

    @classmethod
    def _is_evidence_clustered(cls, item: dict[str, Any]) -> bool:
        return bool(item.get("is_other")) and not cls._is_insufficient_output_evidence(item)

    @staticmethod
    def _contains_normalized_term(text: str, term: str) -> bool:
        return bool(term) and f" {term} " in f" {text} "

    def get_families_csv(self, job_id): return csv_text(self._load_current_result(job_id)["families"], ["family_key", "family_name", "family_description", "member_count", "portfolio_count", "multiple_family_count", "warnings"], list_columns={"warnings"})
    def get_members_csv(self, job_id): return csv_text(self._load_current_result(job_id)["members"], ["family_key", "family_name", "output_cluster", "application_code", "application_name", "portfolio", "confidence", "classification_status", "fields_used", "matched_evidence", "classification_rationale", "warnings"], list_columns={"fields_used", "matched_evidence", "warnings"})
    def get_gaps_csv(self, job_id): return csv_text(self._load_current_result(job_id)["gaps"], ["gap_type", "severity", "family_key", "family_name", "application_code", "application_name", "description", "recommended_action"])
    def get_output_details_csv(self, job_id): return csv_text(self._load_current_result(job_id)["output_details"], ["application_key", "application_name", "output_summary", "output_family_classification", "key_evidence_or_keywords_found", "consumers_or_downstream_users", "confidence_level", "why_classified", "direct_or_inferred", "evidence_type", "missing_data_warnings", "source_of_truth_label", "reliability_label"])
    def get_output_clusters_csv(self, job_id): return csv_text(self._load_current_result(job_id)["output_family_clusters"], ["output_family_name", "applications_producing_this_output_family", "application_count", "specific_outputs_identified", "similarity_notes", "confidence_level", "evidence_type", "source_of_truth_labels_in_cluster", "reliability_labels_in_cluster"])
    def get_output_alerts_csv(self, job_id): return csv_text(self._load_current_result(job_id)["redundancy_alerts"], ["applications_involved", "shared_output_family", "similar_or_duplicated_outputs", "business_impact", "redundancy_severity", "recommendation", "evidence_type", "source_of_truth_label", "reliability_label"])

    def _load_current_preview(self, job_id):
        job = self.job_service.require_job(job_id); ids = job.uploads.get(UploadKind.CMDB.value, [])
        if not ids: raise OutputFamilyAnalysisPrerequisiteError("A current-session CMDB is required.")
        path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(path): raise OutputFamilyAnalysisPrerequisiteError("A parsed CMDB preview is required.")
        preview = self.storage.load_json(path)
        if preview.get("upload_id") != ids[-1]: raise OutputFamilyAnalysisPrerequisiteError("The parsed CMDB preview is stale for the current session.")
        return preview
    def _load_config(self, job_id):
        config = self.upload_config_service.get_output_families_config(job_id)
        if not config.get("usable") or not config.get("families"): raise OutputFamilyAnalysisPrerequisiteError("A current-session Output Family taxonomy is required.")
        return config
    def _load_current_result(self, job_id):
        preview, config, path = self._load_current_preview(job_id), self._load_config(job_id), self._result_path(job_id)
        if not self.storage.exists(path): raise OutputFamilyAnalysisResultNotFoundError("Output classification has not been run for the current session.")
        result = self.storage.load_json(path)
        if result.get("upload_id") != preview.get("upload_id"): raise OutputFamilyAnalysisResultNotFoundError("Output classification has not been run for the current CMDB.")
        if result.get("output_family_config_upload_id") != config.get("upload_id"): raise OutputFamilyAnalysisResultNotFoundError("Output classification has not been run for the current Output Family taxonomy.")
        if result.get("analysis_version") != self.analysis_version: raise OutputFamilyAnalysisResultNotFoundError("Output classification must be rerun for the latest matrix engine.")
        return result
    def _evidence_labels(self, job_id, upload_id):
        path = f"jobs/{job_id}/processed/upload_metadata/{UploadKind.CMDB.value}/{upload_id}.json"; metadata = self.storage.load_json(path) if self.storage.exists(path) else {}
        return f"Current CMDB: {metadata.get('filename') or 'uploaded workbook'}", "Deterministic configured-taxonomy matching from current-session CMDB metadata"
    @classmethod
    def _field(cls, source, aliases):
        normalized = {CMDBParserService.normalize_header(str(k)): v for k, v in source.items()}
        for alias in aliases:
            value = cls._text(normalized.get(CMDBParserService.normalize_header(alias)))
            if value: return value
        return None
    @staticmethod
    def _ordered_unique(values):
        result, seen = [], set()
        for value in values:
            if value.casefold() not in seen: seen.add(value.casefold()); result.append(value)
        return result
    @staticmethod
    def _family_key(name, position): return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or f"family-{position}"
    @staticmethod
    def _normalize(value): return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold().strip(), flags=re.UNICODE).split())
    @staticmethod
    def _text(value):
        if value is None: return None
        text = str(value).strip(); return text or None
    @staticmethod
    def _endpoints(job_id):
        base = f"/api/jobs/{job_id}/analysis/output-families"; e = {"summary": f"{base}/summary", "families": f"{base}/families", "members": f"{base}/members", "gaps": f"{base}/gaps", "application_matrix": f"{base}/application-matrix", "families_csv": f"{base}/families.csv", "members_csv": f"{base}/members.csv", "gaps_csv": f"{base}/gaps.csv", "mvp": f"{base}/mvp", "details_csv": f"{base}/output-details.csv", "clusters_csv": f"{base}/output-clusters.csv", "alerts_csv": f"{base}/output-alerts.csv"}
        return {"summary_endpoint": e["summary"], "families_endpoint": e["families"], "members_endpoint": e["members"], "gaps_endpoint": e["gaps"], "application_matrix_endpoint": e["application_matrix"], "families_csv_endpoint": e["families_csv"], "members_csv_endpoint": e["members_csv"], "gaps_csv_endpoint": e["gaps_csv"], "detail_endpoints": e}
    def _result_path(self, job_id): return f"jobs/{job_id}/results/{self.result_file_name}"
