from __future__ import annotations

import heapq
from itertools import combinations
from math import ceil, isfinite
from math import floor
import re
from time import perf_counter
from typing import Any, Iterable

from app.domain.models import UploadKind
from app.services.cmdb_parser_service import CMDBParserService
from app.services.job_service import JobService
from app.services.result_helpers import bounded_limit, csv_text
from app.storage.base import StorageProvider


class SimilarityPrerequisiteError(ValueError):
    pass


class SimilarityResultNotFoundError(LookupError):
    pass


class _ClusterAccumulator:
    """Deterministic union-find with qualifying-edge averages."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.size = [1] * size
        self.score_sum = [0.0] * size
        self.edge_count = [0] * size
        self.comparable_dimension_sum = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def add_edge(
        self, left: int, right: int, score: float, comparable_dimensions: int
    ) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            self.score_sum[left_root] += score
            self.edge_count[left_root] += 1
            self.comparable_dimension_sum[left_root] += comparable_dimensions
            return
        if (self.size[left_root], -left_root) < (self.size[right_root], -right_root):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]
        self.score_sum[left_root] += self.score_sum[right_root] + score
        self.edge_count[left_root] += self.edge_count[right_root] + 1
        self.comparable_dimension_sum[left_root] += (
            self.comparable_dimension_sum[right_root] + comparable_dimensions
        )


class CMDBSimilarityService:
    """Run and serve deterministic similarity analysis over parsed CMDB records."""

    result_file_name = "similarity.json"
    analysis_version = 3
    stored_heatmap_application_limit = 5_000
    internal_cluster_threshold = 60.0
    stored_redundancy_limit = 200

    # Placeholder values and conversational glue do not describe an
    # application's technology or purpose. Keep them out of every token-overlap
    # calculation so they cannot create either score or evidence.
    overlap_stop_words = frozenset(
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
            "unavailable",
            "yes",
        }
    )

    # Whole-field placeholders are missing values, not business attributes.
    # Keep this separate from overlap_stop_words so values such as
    # "Python, to be provided" can still contribute their meaningful content.
    placeholder_values = frozenset(
        {
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
        "description": ("Description", "Application Description", "App Description"),
        "portfolio": ("Portfolio", "Application Portfolio"),
        "technology_stack": ("Technology Stack", "Tech Stack", "Technologies"),
        "application_technology": (
            "Application Technology",
            "Application Technologies",
        ),
        "platform": ("Platform",),
        "hosting_type": ("Hosting Type", "Hosting"),
        "hosting_provider": ("Hosting Provider", "Cloud Provider"),
        "department": ("Department", "Business Department"),
        "app_classification": (
            "App Classification",
            "Application Classification",
            "Classification",
        ),
    }

    weights = {
        "name": 30.0,
        "description": 20.0,
        "portfolio": 10.0,
        "technology_stack": 15.0,
        "application_technology": 10.0,
        "platform_hosting": 5.0,
        "department": 5.0,
        "app_classification": 5.0,
    }
    default_selected_fields = tuple(weights)
    field_labels = {
        "business_use_case": "Business Use Case",
        "business_function": "Business Function",
        "capability": "Capability",
        "supported_process": "Supported Process",
        "name": "Application Name",
        "description": "Description",
        "portfolio": "Portfolio",
        "technology_stack": "Technology Stack",
        "application_technology": "Application Technology",
        "platform_hosting": "Platform / Hosting",
        "department": "Department",
        "app_classification": "App Classification",
    }
    evidence_rules = (
        "Name and description use normalized sequence and meaningful-token overlap.",
        "Portfolio, department, and application classification use normalized exact matches.",
        "Technology fields use meaningful-token Jaccard overlap with stop words removed.",
        "Platform and hosting compare available platform, hosting type, and provider values.",
        "Generic placeholder values are treated as missing and cannot produce match evidence.",
        "Possible duplicate status is assigned only when the configured duplicate threshold is met.",
        "Missing dimensions are excluded and the configured weights are renormalized across only the dimensions comparable for that pair.",
    )

    cluster_evidence_priority = (
        "Business Function",
        "Capability",
        "Supported Process",
        "Business Use Case",
    )
    functional_dimensions = (
        "business_use_case",
        "business_function",
        "capability",
        "supported_process",
    )

    def __init__(self, storage: StorageProvider, job_service: JobService) -> None:
        self.storage = storage
        self.job_service = job_service

    def run_analysis(
        self,
        job_id: str,
        *,
        similar_pair_threshold: float = 60,
        possible_duplicate_threshold: float = 85,
        max_pairs: int = 5,
        per_application_limit: int = 5,
        selected_fields: list[str] | None = None,
        field_weights: dict[str, Any] | None = None,
        dimension_fields: dict[str, str] | None = None,
        dimension_weights: dict[str, Any] | None = None,
        cluster_threshold: float | None = None,
        heatmap_limit: int = 50,
        alert_limit: int = 200,
    ) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        preview_path = f"jobs/{job_id}/processed/cmdb_preview.json"
        if not self.storage.exists(preview_path):
            raise SimilarityPrerequisiteError(
                "Similarity analysis requires a parsed CMDB upload for this job"
            )
        preview = self.storage.load_json(preview_path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        upload_id = preview.get("upload_id")
        if not uploads or upload_id != uploads[-1]:
            raise SimilarityPrerequisiteError(
                "Similarity analysis requires the latest CMDB upload to be parsed"
            )

        records = preview.get("applications", [])
        if not isinstance(records, list):
            raise SimilarityPrerequisiteError("The parsed CMDB preview is invalid")
        if preview.get("total_row_count") != len(records):
            raise SimilarityPrerequisiteError(
                "The parsed CMDB preview does not contain all normalized application records; upload the CMDB again before running similarity"
            )
        analysis_started = perf_counter()
        columns = preview.get("columns", [])
        resolved = self._resolve_columns(columns)
        if dimension_fields is not None:
            (
                selected_fields_used,
                field_weights_used,
                dimension_fields_used,
            ) = self._resolve_dimension_config(
                dimension_fields, dimension_weights, columns
            )
            unsupported_fields: list[str] = []
            config_warnings: list[str] = []
        else:
            (
                selected_fields_used,
                field_weights_used,
                unsupported_fields,
                config_warnings,
            ) = self._resolve_scoring_config(selected_fields, field_weights, columns)
            dimension_fields_used = {}
        applications = [
            self._prepare_record(item, preview, resolved, dimension_fields_used)
            for item in records
        ]
        comparison_applications = self._deduplicate_applications(applications)
        warnings = config_warnings + self._analysis_warnings(
            job_id, upload_id, preview, applications
        )

        if not any(
            application["normalized"].get(field, "")
            for application in comparison_applications
            for field in selected_fields_used
            if field_weights_used.get(field, 0) > 0
        ):
            raise SimilarityPrerequisiteError(
                "The weighted similarity fields contain no comparable values in the current CMDB"
            )

        # Cluster grouping is deliberately internal in the MVP. Accept an old
        # payload value without failing, but do not let it alter new analysis.
        del cluster_threshold
        cluster_threshold_used = self.internal_cluster_threshold
        pair_heap: list[tuple[float, int, dict[str, Any]]] = []
        alert_heap: list[tuple[float, int, dict[str, Any]]] = []
        cluster_accumulator = _ClusterAccumulator(len(comparison_applications))
        evaluated = 0
        comparable_pairs = 0
        similar_pair_count = 0
        duplicate_count = 0
        pair_order = 0
        candidate_postings = self._candidate_postings(
            comparison_applications, selected_fields_used, field_weights_used
        )
        candidate_pairs = self._candidate_pairs(
            comparison_applications,
            selected_fields_used,
            field_weights_used,
            # Missing dimensions are renormalized per pair, so a raw-weight
            # upper-bound cannot safely prune candidates by the final score.
            0,
            postings=candidate_postings,
        )
        for left_index, right_index in candidate_pairs:
            left = comparison_applications[left_index]
            right = comparison_applications[right_index]
            if self._same_effective_identity(left, right):
                continue
            evaluated += 1
            pair = self._score_pair(
                left,
                right,
                possible_duplicate_threshold,
                selected_fields_used,
                field_weights_used,
            )
            comparable_dimension_count = pair.pop("comparable_dimension_count")
            if comparable_dimension_count == 0:
                continue
            comparable_pairs += 1
            if pair["similarity_score"] >= similar_pair_threshold:
                similar_pair_count += 1
            if pair["possible_duplicate"]:
                duplicate_count += 1
                self._push_bounded(
                    alert_heap,
                    pair,
                    self.stored_redundancy_limit,
                    pair_order,
                )
            self._push_bounded(pair_heap, pair, max_pairs, pair_order)
            if pair["similarity_score"] >= cluster_threshold_used:
                cluster_accumulator.add_edge(
                    left_index,
                    right_index,
                    pair["similarity_score"],
                    comparable_dimension_count,
                )
            pair_order += 1

        pairs = self._sorted_heap(pair_heap)
        alerts = self._sorted_heap(alert_heap)
        clusters = self._build_clusters(
            cluster_accumulator, comparison_applications, selected_fields_used
        )
        if evaluated and not comparable_pairs:
            warnings.append(
                "No application pairs contained comparable values in the configured CMDB fields."
            )
        analysis_status = "completed_with_warnings" if warnings else "completed"
        rules_config = {
            "scoring_method": "deterministic",
            "selected_fields_used": selected_fields_used,
            "field_weights_used": field_weights_used,
            "dimension_fields_used": dimension_fields_used,
            "cluster_threshold": cluster_threshold_used,
            "similar_pair_threshold": float(similar_pair_threshold),
            "possible_duplicate_threshold": float(possible_duplicate_threshold),
            "max_pairs": max_pairs,
            "per_application_limit": per_application_limit,
            "heatmap_limit": heatmap_limit,
            "alert_limit": self.stored_redundancy_limit,
            "stop_words_applied": True,
            "evidence_rules": list(self.evidence_rules),
            "unsupported_fields": unsupported_fields,
            "warnings": warnings,
        }
        analysis_elapsed_seconds = perf_counter() - analysis_started
        summary = {
            "total_applications_analyzed": len(applications),
            "total_candidate_pairs_evaluated": evaluated,
            "analysis_elapsed_seconds": round(analysis_elapsed_seconds, 6),
            "similar_pair_count": similar_pair_count,
            "possible_duplicate_count": duplicate_count,
            "similar_pair_threshold": float(similar_pair_threshold),
            "possible_duplicate_threshold": float(possible_duplicate_threshold),
            "source_of_truth_label": "Source of Truth 1",
            "reliability_label": "Average",
            "warning_count": len(warnings),
        }
        result = {
            "status": "analyzed",
            "module_name": "similarity",
            "job_id": job_id,
            "upload_id": upload_id,
            "analysis_status": analysis_status,
            "analysis_version": self.analysis_version,
            "summary": summary,
            "top_similar_pairs": pairs,
            # Kept for older consumers; tab-specific results are computed from
            # the preprocessed state and are never embedded for every app.
            "similar_apps_by_application": [],
            "redundancy_alerts": alerts,
            "clusters": clusters,
            "analysis_state": {
                "applications": [
                    self._serializable_application(application, index)
                    for index, application in enumerate(comparison_applications)
                ],
                "candidate_postings": candidate_postings,
                "portfolio_field": self._portfolio_field(columns),
            },
            "selected_fields_used": selected_fields_used,
            "field_weights_used": field_weights_used,
            "unsupported_fields": unsupported_fields,
            "rules_config": rules_config,
            "warnings": warnings,
            "per_application_limit": per_application_limit,
            "heatmap_limit": heatmap_limit,
            "alert_limit": self.stored_redundancy_limit,
        }
        self.storage.save_json(self._result_path(job_id), result)
        return result

    def get_overview(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return self._overview(result)

    def get_summary(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return {
            "status": result["status"],
            "module_name": result["module_name"],
            "job_id": result["job_id"],
            "upload_id": result["upload_id"],
            "analysis_status": result["analysis_status"],
            "summary": result["summary"],
            "warnings": result["warnings"],
        }

    def get_pairs(self, job_id: str, page: int, page_size: int) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        pairs = result.get("top_similar_pairs", [])
        total_records = len(pairs)
        start = (page - 1) * page_size
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": ceil(total_records / page_size) if total_records else 0,
            "records": pairs[start : start + page_size],
        }

    def get_apps(
        self,
        job_id: str,
        application_key: str | None = None,
        limit: int = 5,
        portfolio: str = "",
        excluded_application_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, 50)
        applications = self._state_applications(result)
        normalized_portfolio = self._normalize_text(portfolio)
        excluded_keys = {
            key.strip() for key in (excluded_application_keys or []) if key.strip()
        }
        if not applications:
            groups: list[dict[str, Any]] = []
        elif application_key is None:
            # Compatibility path for older callers. It is intentionally not
            # used by the redesigned UI because expanding every app is bulky.
            groups = [
                self._similar_apps_group(
                    index,
                    applications,
                    result,
                    safe_limit,
                    normalized_portfolio,
                    excluded_keys,
                )
                for index in range(len(applications))
            ]
        else:
            selected_index = next(
                (
                    index
                    for index, application in enumerate(applications)
                    if application["application_key"] == application_key
                ),
                None,
            )
            if selected_index is None:
                raise SimilarityResultNotFoundError(
                    f"Unknown current-CMDB application key '{application_key}'"
                )
            groups = [
                self._similar_apps_group(
                    selected_index,
                    applications,
                    result,
                    safe_limit,
                    normalized_portfolio,
                    excluded_keys,
                )
            ]
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "per_application_limit": safe_limit,
            "applications": groups,
        }

    def get_rules(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        applications = self._state_applications(result)
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "rules_config": result["rules_config"],
            "applications": [
                self._application_reference(application)
                for application in applications
            ],
            "portfolio_options": sorted(
                {app["portfolio"] for app in applications if app["portfolio"]},
                key=str.casefold,
            ),
        }

    def get_heatmap(
        self,
        job_id: str,
        limit: int,
        search: str = "",
        portfolio: str = "",
        application_key: str = "",
        score_range: str = "20-100",
        excluded_application_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, self.stored_heatmap_application_limit)
        state_applications = self._state_applications(result)
        portfolio_options = sorted(
            {app["portfolio"] for app in state_applications if app["portfolio"]},
            key=str.casefold,
        )
        normalized_portfolio = self._normalize_text(portfolio)
        normalized_application_key = application_key.strip()
        excluded_keys = {
            key.strip() for key in (excluded_application_keys or []) if key.strip()
        }
        candidate_scope = [
            app
            for app in state_applications
            if app["application_key"] not in excluded_keys
            and (
                not normalized_portfolio
                or app["normalized_portfolio"] == normalized_portfolio
            )
        ]
        score_filter = self._score_range(score_range)
        if not normalized_application_key:
            normalized_search = self._normalize_text(search)
            anchor_scope = [
                app
                for app in candidate_scope
                if not normalized_search
                or normalized_search
                in self._normalize_text(f"{app['name']} {app['code']}")
            ]
            rules = result["rules_config"]
            selected_fields = list(rules["selected_fields_used"])
            field_weights = dict(rules["field_weights_used"])
            duplicate_threshold = float(rules["possible_duplicate_threshold"])
            ranked_anchors, strongest, score_cache = self._rank_heatmap_applications(
                anchor_scope,
                candidate_scope,
                selected_fields,
                field_weights,
                duplicate_threshold,
                safe_limit,
                score_filter=score_filter,
            )
            candidate_cache = score_cache
            if normalized_search:
                candidate_indexes, candidate_cache = self._heatmap_candidates(
                    ranked_anchors,
                    candidate_scope,
                    selected_fields,
                    field_weights,
                    duplicate_threshold,
                    safe_limit,
                    score_filter=score_filter,
                )
                ranked_candidates = [
                    candidate_scope[index] for index in candidate_indexes
                ]
            else:
                # In all-app mode, show the same bounded application set on
                # both axes. Only in-range comparable pairs become colored
                # cells; other positions remain visibly empty in the matrix.
                ranked_candidates = ranked_anchors
            matrix: list[dict[str, Any]] = []
            for anchor_index, anchor in enumerate(ranked_anchors):
                visible_candidates = (
                    ranked_candidates
                    if normalized_search
                    else ranked_candidates[anchor_index + 1 :]
                )
                for candidate in visible_candidates:
                    if self._same_effective_identity(anchor, candidate):
                        continue
                    pair = candidate_cache.get(
                        self._pair_cache_key(anchor, candidate)
                    )
                    if pair is None:
                        pair = self._score_pair(
                            anchor,
                            candidate,
                            duplicate_threshold,
                            selected_fields,
                            field_weights,
                        )
                    if pair is None or not self._score_in_range(
                        pair["similarity_score"], score_filter
                    ):
                        continue
                    matrix.append(
                        {
                            "anchor_application_key": anchor["application_key"],
                            "anchor_application_code": anchor["code"],
                            "anchor_application_name": anchor["name"],
                            "candidate_application_key": candidate["application_key"],
                            "candidate_application_code": candidate["code"],
                            "candidate_application_name": candidate["name"],
                            "candidate_portfolio": candidate["portfolio"],
                            "similarity_score": self._displayed_score(
                                pair["similarity_score"]
                            ),
                            "possible_duplicate": pair["possible_duplicate"],
                        }
                    )
            strongest_candidate_scores = {
                app["application_key"]: max(
                    (
                        float(pair["similarity_score"])
                        for anchor in ranked_anchors
                        if (
                            pair := candidate_cache.get(
                                self._pair_cache_key(anchor, app)
                            )
                        ) is not None
                    ),
                    default=0.0,
                )
                for app in ranked_candidates
            }
            return {
                "job_id": job_id,
                "upload_id": result["upload_id"],
                "limit": safe_limit,
                "matched_anchor_count": len(anchor_scope),
                "candidate_count": len(ranked_candidates),
                "no_comparable_data": bool(anchor_scope) and not matrix,
                "portfolio_options": portfolio_options,
                "anchor_applications": [
                    self._application_reference(
                        app,
                        self._displayed_score(strongest[app["application_key"]])
                        if strongest[app["application_key"]]
                        else None,
                    )
                    for app in ranked_anchors
                ],
                "candidate_applications": [
                    self._application_reference(
                        app,
                        self._displayed_score(
                            strongest_candidate_scores[app["application_key"]]
                        )
                        if strongest_candidate_scores[app["application_key"]]
                        else None,
                    )
                    for app in ranked_candidates
                ],
                "matrix": matrix,
                "warnings": result.get("warnings", []),
                "score_range": score_range,
                "score_range_note": self._score_range_note(score_range),
            }

        anchor = next(
            (
                app
                for app in state_applications
                if app["application_key"] == normalized_application_key
            ),
            None,
        )
        if anchor is None:
            raise SimilarityResultNotFoundError(
                f"Unknown current-CMDB application key '{application_key}'"
            )

        candidate_scope = [
            app
            for app in state_applications
            if not self._same_effective_identity(anchor, app)
            and app["application_key"] not in excluded_keys
            and (
                not normalized_portfolio
                or app["normalized_portfolio"] == normalized_portfolio
            )
            and (
                not self._normalize_text(search)
                or self._normalize_text(search)
                in self._normalize_text(f"{app['name']} {app['code']}")
            )
        ]
        rules = result["rules_config"]
        selected_fields = list(rules["selected_fields_used"])
        field_weights = dict(rules["field_weights_used"])
        duplicate_threshold = float(rules["possible_duplicate_threshold"])
        matches: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for candidate in candidate_scope:
            pair = self._score_pair(
                anchor,
                candidate,
                duplicate_threshold,
                selected_fields,
                field_weights,
            )
            if pair["comparable_dimension_count"] == 0:
                continue
            displayed_score = self._displayed_score(pair["similarity_score"])
            if not self._score_in_range(displayed_score, score_filter):
                continue
            matches.append((displayed_score, candidate, pair))

        matches.sort(
            key=lambda item: (
                -item[0],
                self._normalize_text(item[1]["name"]),
                self._normalize_text(item[1]["code"]),
                item[1]["application_key"],
            )
        )
        matched_candidate_count = len(matches)
        visible_matches = matches[:safe_limit]
        candidates = [candidate for _, candidate, _ in visible_matches]
        matrix = [
            {
                "anchor_application_key": anchor["application_key"],
                "anchor_application_code": anchor["code"],
                "anchor_application_name": anchor["name"],
                "candidate_application_key": candidate["application_key"],
                "candidate_application_code": candidate["code"],
                "candidate_application_name": candidate["name"],
                "candidate_portfolio": candidate["portfolio"],
                "similarity_score": displayed_score,
                "possible_duplicate": pair["possible_duplicate"],
            }
            for displayed_score, candidate, pair in visible_matches
        ]
        strongest_score = visible_matches[0][0] if visible_matches else None
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "matched_anchor_count": 1,
            "candidate_count": matched_candidate_count,
            "no_comparable_data": not matrix,
            "portfolio_options": portfolio_options,
            "anchor_applications": [
                self._application_reference(anchor, strongest_score)
            ],
            "candidate_applications": [
                self._application_reference(
                    candidate,
                    visible_matches[index][0],
                )
                for index, candidate in enumerate(candidates)
            ],
            "matrix": matrix,
            "warnings": result.get("warnings", []),
            "score_range": score_range,
            "score_range_note": self._score_range_note(score_range),
        }

    @classmethod
    def _rank_heatmap_applications(
        cls,
        scoped_applications: list[dict[str, Any]],
        all_applications: list[dict[str, Any]],
        selected_fields: list[str],
        weights: dict[str, float],
        duplicate_threshold: float,
        limit: int,
        postings: dict[str, dict[str, list[int]]] | None = None,
        score_filter: tuple[int, int] = (20, 100),
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, float],
        dict[tuple[str, str], dict[str, Any]],
    ]:
        """Rank a filtered scope by each app's strongest non-self score.

        The stored inverted index supplies every pair capable of a positive
        score. Apps without a positive-overlap candidate retain a strongest
        score of zero, avoiding an all-pairs rescan when 25/50/100 changes.
        """
        if postings is None:
            postings = cls._candidate_postings(all_applications, selected_fields, weights)
        posting_work = sum(
            len(postings.get(field, {}).get(token, ()))
            for anchor in scoped_applications
            for field in selected_fields
            if weights.get(field, 0) > 0
            for token in anchor["tokens"].get(field, set())
        )
        pairwise_work = len(scoped_applications) * len(all_applications)
        if pairwise_work > 250_000 and posting_work > pairwise_work // 5:
            return cls._rank_heatmap_applications_bitset(
                scoped_applications,
                all_applications,
                selected_fields,
                weights,
                duplicate_threshold,
                limit,
                score_filter,
            )
        index_by_key = {
            app["application_key"]: index for index, app in enumerate(all_applications)
        }
        scoped_keys = {app["application_key"] for app in scoped_applications}
        strongest = {key: 0.0 for key in scoped_keys}
        score_cache: dict[tuple[str, str], dict[str, Any]] = {}
        for anchor in scoped_applications:
            possible_indexes: set[int] = set()
            for field in selected_fields:
                if weights.get(field, 0) <= 0:
                    continue
                for token in anchor["tokens"].get(field, set()):
                    possible_indexes.update(postings.get(field, {}).get(token, ()))
            for candidate_index in possible_indexes:
                candidate = all_applications[candidate_index]
                if (
                    cls._same_effective_identity(anchor, candidate)
                ):
                    continue
                cache_key = cls._pair_cache_key(anchor, candidate)
                pair = score_cache.get(cache_key)
                if pair is None:
                    pair = cls._score_pair(
                        anchor,
                        candidate,
                        duplicate_threshold,
                        selected_fields,
                        weights,
                    )
                    score_cache[cache_key] = pair
                if pair["comparable_dimension_count"] and cls._score_in_range(
                    pair["similarity_score"], score_filter
                ):
                    pair_score = float(pair["similarity_score"])
                    strongest[anchor["application_key"]] = max(
                        strongest[anchor["application_key"]], pair_score
                    )
        ranked = sorted(
            scoped_applications,
            key=lambda app: (
                -strongest[app["application_key"]],
                cls._normalize_text(app["name"]),
                cls._normalize_text(app["code"]),
                index_by_key.get(app["application_key"], 0),
            ),
        )
        return ranked[:limit], strongest, score_cache

    @classmethod
    def _rank_heatmap_applications_bitset(
        cls,
        scoped_applications: list[dict[str, Any]],
        all_applications: list[dict[str, Any]],
        selected_fields: list[str],
        weights: dict[str, float],
        duplicate_threshold: float,
        limit: int,
        score_filter: tuple[int, int],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, float],
        dict[tuple[str, str], dict[str, Any]],
    ]:
        """Rank a dense scope with bitset Jaccard scores and bounded memory."""
        del duplicate_threshold  # Duplicate labels do not affect ranking.
        token_bits: dict[str, dict[str, int]] = {field: {} for field in selected_fields}
        masks: list[dict[str, int]] = []
        lengths: list[dict[str, int]] = []
        comparable: list[dict[str, bool]] = []
        for application in all_applications:
            app_masks: dict[str, int] = {}
            app_lengths: dict[str, int] = {}
            app_comparable: dict[str, bool] = {}
            for field in selected_fields:
                tokens = application["tokens"].get(field, set())
                bits = token_bits[field]
                mask = 0
                for token in tokens:
                    ordinal = bits.get(token)
                    if ordinal is None:
                        ordinal = len(bits)
                        bits[token] = ordinal
                    mask |= 1 << ordinal
                app_masks[field] = mask
                app_lengths[field] = len(tokens)
                app_comparable[field] = bool(
                    weights.get(field, 0) > 0
                    and application["normalized"].get(field, "")
                )
            masks.append(app_masks)
            lengths.append(app_lengths)
            comparable.append(app_comparable)

        all_index_by_key = {
            app["application_key"]: index
            for index, app in enumerate(all_applications)
        }
        scoped_indexes = {
            app["application_key"]: all_index_by_key[app["application_key"]]
            for app in scoped_applications
        }
        strongest = {key: 0.0 for key in scoped_indexes}
        for anchor in scoped_applications:
            left_index = all_index_by_key[anchor["application_key"]]
            for right_index, candidate in enumerate(all_applications):
                if cls._same_effective_identity(anchor, candidate):
                    continue
                candidate_scoped_index = scoped_indexes.get(candidate["application_key"])
                if candidate_scoped_index is not None and candidate_scoped_index < left_index:
                    continue

                weighted_score = 0.0
                comparable_weight = 0.0
                for field in selected_fields:
                    weight = weights.get(field, 0.0)
                    if not (
                        weight > 0
                        and comparable[left_index][field]
                        and comparable[right_index][field]
                    ):
                        continue
                    comparable_weight += weight
                    left_value = anchor["normalized"].get(field, "")
                    right_value = candidate["normalized"].get(field, "")
                    if left_value == right_value:
                        weighted_score += weight
                        continue
                    intersection = (masks[left_index][field] & masks[right_index][field]).bit_count()
                    if intersection:
                        union = (
                            lengths[left_index][field]
                            + lengths[right_index][field]
                            - intersection
                        )
                        weighted_score += weight * intersection / union

                if comparable_weight == 0:
                    continue
                pair_score = round(weighted_score / comparable_weight * 100, 2)
                if not cls._score_in_range(pair_score, score_filter):
                    continue
                strongest[anchor["application_key"]] = max(
                    strongest[anchor["application_key"]], pair_score
                )
                if candidate_scoped_index is not None:
                    strongest[candidate["application_key"]] = max(
                        strongest[candidate["application_key"]], pair_score
                    )

        ranked = sorted(
            scoped_applications,
            key=lambda app: (
                -strongest[app["application_key"]],
                cls._normalize_text(app["name"]),
                cls._normalize_text(app["code"]),
                all_index_by_key.get(app["application_key"], 0),
            ),
        )
        return ranked[:limit], strongest, {}

    @staticmethod
    def _pair_cache_key(
        left: dict[str, Any], right: dict[str, Any]
    ) -> tuple[str, str]:
        return tuple(sorted((left["application_key"], right["application_key"])))

    @classmethod
    def _heatmap_candidates(
        cls,
        anchors: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        selected_fields: list[str],
        weights: dict[str, float],
        duplicate_threshold: float,
        limit: int,
        postings: dict[str, dict[str, list[int]]] | None = None,
        score_filter: tuple[int, int] = (20, 100),
    ) -> tuple[list[int], dict[tuple[str, str], dict[str, Any]]]:
        """Return globally ranked candidates drawn from each anchor's best matches.

        The postings index is exact for positive exact/Jaccard scores: applications
        sharing no weighted token can only score zero. This keeps heatmap filtering
        on reusable preprocessed state without evaluating the enterprise all-pairs
        product or padding the columns with zero-score applications.
        """
        if postings is None:
            postings = cls._candidate_postings(
                applications, selected_fields, weights
            )

        score_cache: dict[tuple[str, str], dict[str, Any]] = {}
        strongest_by_candidate: dict[int, float] = {}
        for anchor in anchors:
            possible_indexes: set[int] = set()
            for field in selected_fields:
                if weights.get(field, 0) <= 0:
                    continue
                for token in anchor["tokens"].get(field, set()):
                    possible_indexes.update(
                        postings.get(field, {}).get(token, ())
                    )

            strongest_for_anchor: list[tuple[float, int]] = []
            for candidate_index in possible_indexes:
                candidate = applications[candidate_index]
                if cls._same_effective_identity(anchor, candidate):
                    continue
                pair = cls._score_pair(
                    anchor,
                    candidate,
                    duplicate_threshold,
                    selected_fields,
                    weights,
                )
                if (
                    pair["comparable_dimension_count"] == 0
                    or not cls._score_in_range(
                        pair["similarity_score"], score_filter
                    )
                ):
                    continue
                score_cache[cls._pair_cache_key(anchor, candidate)] = pair
                strongest_for_anchor.append(
                    (float(pair["similarity_score"]), candidate_index)
                )

            if score_filter[0] == 0 and len(strongest_for_anchor) < limit:
                # Pairs with no shared weighted token can only score zero. Find
                # enough comparable zero-score candidates to fill the bounded
                # result, without scoring every possible pair in the portfolio.
                needed = limit - len(strongest_for_anchor)
                for candidate_index, candidate in enumerate(applications):
                    if (
                        candidate_index in possible_indexes
                        or cls._same_effective_identity(anchor, candidate)
                    ):
                        continue
                    pair = cls._score_pair(
                        anchor,
                        candidate,
                        duplicate_threshold,
                        selected_fields,
                        weights,
                    )
                    if (
                        pair["comparable_dimension_count"] > 0
                        and cls._score_in_range(pair["similarity_score"], score_filter)
                    ):
                        score_cache[cls._pair_cache_key(anchor, candidate)] = pair
                        strongest_for_anchor.append(
                            (float(pair["similarity_score"]), candidate_index)
                        )
                        needed -= 1
                        if needed == 0:
                            break

            strongest_for_anchor.sort(key=lambda item: (-item[0], item[1]))
            for score, candidate_index in strongest_for_anchor[:limit]:
                strongest_by_candidate[candidate_index] = max(
                    score, strongest_by_candidate.get(candidate_index, 0.0)
                )

        ranked = sorted(
            strongest_by_candidate,
            key=lambda index: (-strongest_by_candidate[index], index),
        )
        return ranked[:limit], score_cache

    def get_alerts(
        self,
        job_id: str,
        limit: int,
        score_range: str = "20-100",
        portfolio: str = "",
        excluded_application_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        safe_limit = bounded_limit(limit, self.stored_redundancy_limit)
        score_filter = self._score_range(score_range)
        applications = self._state_applications(result)
        application_by_code = {
            self._normalize_text(app["code"]): app for app in applications
        }
        normalized_portfolio = self._normalize_text(portfolio)
        excluded_keys = {
            key.strip() for key in (excluded_application_keys or []) if key.strip()
        }
        pairs = [
            pair
            for pair in result.get("redundancy_alerts", [])
            if self._score_in_range(pair.get("similarity_score", 0), score_filter)
            and (app_a := application_by_code.get(
                self._normalize_text(pair.get("application_code_a", ""))
            )) is not None
            and (app_b := application_by_code.get(
                self._normalize_text(pair.get("application_code_b", ""))
            )) is not None
            and app_a["application_key"] not in excluded_keys
            and app_b["application_key"] not in excluded_keys
            and (
                not normalized_portfolio
                or normalized_portfolio
                in {
                    app_a["normalized_portfolio"],
                    app_b["normalized_portfolio"],
                }
            )
        ]
        alerts = []
        for pair in pairs[:safe_limit]:
            app_a = application_by_code[
                self._normalize_text(pair.get("application_code_a", ""))
            ]
            app_b = application_by_code[
                self._normalize_text(pair.get("application_code_b", ""))
            ]
            possible_duplicate = bool(pair["possible_duplicate"])
            alerts.append(
                {
                    "alert_type": (
                        "possible_duplicate" if possible_duplicate else "high_similarity"
                    ),
                    "severity": "critical" if possible_duplicate else "warning",
                    "application_code_a": pair["application_code_a"],
                    "application_name_a": pair["application_name_a"],
                    "application_code_b": pair["application_code_b"],
                    "application_name_b": pair["application_name_b"],
                    "application_key_a": app_a["application_key"],
                    "application_key_b": app_b["application_key"],
                    "portfolio_a": app_a["portfolio"],
                    "portfolio_b": app_b["portfolio"],
                    "similarity_score": pair["similarity_score"],
                    "evidence": pair.get("evidence", []),
                    "matched_fields": pair.get("matched_fields", []),
                    "recommendation": self._recommendation(possible_duplicate),
                    "redundancy_reason": pair.get("similarity_reason", ""),
                    "component_details": pair.get("component_details", {}),
                }
            )
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "limit": safe_limit,
            "total_alert_count": len(pairs),
            "alerts": alerts,
            "warnings": result.get("warnings", []),
        }

    def get_clusters(self, job_id: str) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "clusters": result.get("clusters", []),
            "warnings": result.get("warnings", []),
        }

    def compare(
        self, job_id: str, application_code_a: str, application_code_b: str
    ) -> dict[str, Any]:
        result = self._load_current_result(job_id)
        normalized_a = self._normalize_text(application_code_a)
        normalized_b = self._normalize_text(application_code_b)
        if normalized_a == normalized_b:
            raise SimilarityPrerequisiteError(
                "Direct comparison requires two different Application Codes"
            )

        preview = self.storage.load_json(
            f"jobs/{job_id}/processed/cmdb_preview.json"
        )
        resolved = self._resolve_columns(preview.get("columns", []))
        rules = result["rules_config"]
        prepared = [
            self._prepare_record(
                record,
                preview,
                resolved,
                dict(rules.get("dimension_fields_used", {})),
            )
            for record in preview.get("applications", [])
        ]
        by_code: dict[str, dict[str, Any]] = {}
        for application in prepared:
            normalized_code = self._normalize_text(application["primary_code"])
            if normalized_code:
                by_code.setdefault(normalized_code, application)
        missing_codes = [
            code
            for normalized, code in (
                (normalized_a, application_code_a),
                (normalized_b, application_code_b),
            )
            if normalized not in by_code
        ]
        if missing_codes:
            raise SimilarityResultNotFoundError(
                "Unknown Application Code(s): " + ", ".join(missing_codes)
            )
        left = by_code[normalized_a]
        right = by_code[normalized_b]

        stored_pair = next(
            (
                pair
                for pair in result.get("top_similar_pairs", [])
                if {
                    self._normalize_text(pair["application_code_a"]),
                    self._normalize_text(pair["application_code_b"]),
                }
                == {normalized_a, normalized_b}
            ),
            None,
        )
        if stored_pair is None:
            pair = self._score_pair(
                left,
                right,
                float(rules["possible_duplicate_threshold"]),
                list(rules["selected_fields_used"]),
                dict(rules["field_weights_used"]),
            )
        else:
            pair = stored_pair

        comparable = pair.get("comparable_dimension_count", 1) > 0

        return {
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "application_a": self._comparison_application(left),
            "application_b": self._comparison_application(right),
            "similarity_score": pair["similarity_score"] if comparable else None,
            "possible_duplicate": pair["possible_duplicate"] if comparable else False,
            "evidence": pair.get("evidence", []),
            "matched_fields": pair.get("matched_fields", []),
            "differing_fields": pair.get("differing_fields", []),
            "missing_fields": pair.get("missing_fields", []),
            "recommendation": (
                self._recommendation(pair["possible_duplicate"])
                if comparable
                else "No rationalization recommendation is available because the applications have no comparable functional evidence."
            ),
            "from_stored_result": stored_pair is not None,
        }

    def get_results_csv(self, job_id: str) -> str:
        result = self._load_current_result(job_id)
        columns = [
            "application_code_a",
            "application_name_a",
            "application_code_b",
            "application_name_b",
            "similarity_score",
            "possible_duplicate",
            "evidence",
            "matched_fields",
            "missing_fields",
        ]
        return csv_text(
            result.get("top_similar_pairs", []),
            columns,
            list_columns={"evidence", "matched_fields", "missing_fields"},
        )

    def _overview(self, result: dict[str, Any]) -> dict[str, Any]:
        job_id = result["job_id"]
        return {
            "status": result["status"],
            "module_name": result["module_name"],
            "job_id": job_id,
            "upload_id": result["upload_id"],
            "analysis_status": result["analysis_status"],
            "summary": result["summary"],
            "top_similar_pairs": result["top_similar_pairs"],
            "selected_fields_used": result["selected_fields_used"],
            "field_weights_used": result["field_weights_used"],
            "unsupported_fields": result["unsupported_fields"],
            "rules_config": result["rules_config"],
            "warnings": result["warnings"],
            "summary_endpoint": f"/api/jobs/{job_id}/analysis/similarity/summary",
            "pairs_endpoint": f"/api/jobs/{job_id}/analysis/similarity/pairs?page=1&page_size=50",
            "apps_endpoint": f"/api/jobs/{job_id}/analysis/similarity/apps",
            "rules_endpoint": f"/api/jobs/{job_id}/analysis/similarity/rules",
            "heatmap_endpoint": f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=50",
            "alerts_endpoint": f"/api/jobs/{job_id}/analysis/similarity/alerts?limit=25",
            "clusters_endpoint": f"/api/jobs/{job_id}/analysis/similarity/clusters",
            "compare_endpoint": f"/api/jobs/{job_id}/analysis/similarity/compare",
            "csv_endpoint": f"/api/jobs/{job_id}/analysis/similarity/results.csv",
            "detail_endpoints": {
                "summary": f"/api/jobs/{job_id}/analysis/similarity/summary",
                "pairs": f"/api/jobs/{job_id}/analysis/similarity/pairs?page=1&page_size=50",
                "applications": f"/api/jobs/{job_id}/analysis/similarity/apps",
                "rules": f"/api/jobs/{job_id}/analysis/similarity/rules",
                "heatmap": f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=50",
                "alerts": f"/api/jobs/{job_id}/analysis/similarity/alerts?limit=25",
                "clusters": f"/api/jobs/{job_id}/analysis/similarity/clusters",
                "compare": f"/api/jobs/{job_id}/analysis/similarity/compare",
                "csv": f"/api/jobs/{job_id}/analysis/similarity/results.csv",
            },
        }

    def _load_current_result(self, job_id: str) -> dict[str, Any]:
        job = self.job_service.require_job(job_id)
        path = self._result_path(job_id)
        if not self.storage.exists(path):
            raise SimilarityResultNotFoundError(
                f"Similarity analysis has not been run for job '{job_id}'"
            )
        result = self.storage.load_json(path)
        uploads = job.uploads.get(UploadKind.CMDB.value, [])
        if not uploads or result.get("upload_id") != uploads[-1]:
            raise SimilarityResultNotFoundError(
                f"Similarity analysis has not been run for the latest CMDB upload for job '{job_id}'"
            )
        if result.get("analysis_version") != self.analysis_version:
            raise SimilarityResultNotFoundError(
                "Similarity analysis must be rerun with the functional-dimension scoring model"
            )
        return result

    @classmethod
    def _resolve_scoring_config(
        cls,
        selected_fields: list[str] | None,
        field_weights: dict[str, Any] | None,
        columns: Iterable[Any] = (),
    ) -> tuple[list[str], dict[str, float], list[str], list[str]]:
        text_columns = [str(column) for column in columns]
        unsupported_fields: list[str] = []
        warnings: list[str] = []
        if selected_fields is None:
            selected = list(cls.default_selected_fields)
        else:
            selected = []
            for requested in selected_fields:
                field = cls._resolve_requested_field(requested, text_columns)
                if field is None:
                    if requested not in unsupported_fields:
                        unsupported_fields.append(requested)
                    continue
                if field not in selected:
                    selected.append(field)
            if unsupported_fields:
                raise SimilarityPrerequisiteError(
                    "Configured similarity fields are not available in the current CMDB: "
                    + ", ".join(str(item) for item in unsupported_fields)
                )
            if not selected:
                raise SimilarityPrerequisiteError(
                    "Select at least one valid current CMDB field for similarity analysis"
                )

        configured_weights = {
            field: cls.weights.get(field, 1.0) for field in selected
        }
        for requested, raw_weight in (field_weights or {}).items():
            field = cls._resolve_requested_field(requested, text_columns)
            if field is None:
                raise SimilarityPrerequisiteError(
                    f"Similarity weight field '{requested}' is not available in the current CMDB"
                )
            if field not in configured_weights:
                raise SimilarityPrerequisiteError(
                    f"Similarity weight field '{requested}' is not selected"
                )
            if (
                isinstance(raw_weight, bool)
                or not isinstance(raw_weight, (int, float))
                or not isfinite(float(raw_weight))
                or float(raw_weight) < 0
            ):
                raise SimilarityPrerequisiteError(
                    f"Similarity weight for '{requested}' must be a non-negative number"
                )
            configured_weights[field] = float(raw_weight)

        total_weight = sum(configured_weights.values())
        if not total_weight:
            raise SimilarityPrerequisiteError(
                "At least one similarity weight must be greater than zero"
            )
        normalized_weights = {
            field: round(weight / total_weight * 100, 6)
            for field, weight in configured_weights.items()
        }
        return selected, normalized_weights, unsupported_fields, warnings

    @classmethod
    def _resolve_dimension_config(
        cls,
        dimension_fields: dict[str, str],
        dimension_weights: dict[str, Any] | None,
        columns: Iterable[Any],
    ) -> tuple[list[str], dict[str, float], dict[str, str]]:
        text_columns = [str(column) for column in columns]
        if set(dimension_fields) != set(cls.functional_dimensions):
            raise SimilarityPrerequisiteError(
                "Similarity analysis requires Business Use Case, Business Function, Capability, and Supported Process mappings"
            )
        resolved: dict[str, str] = {}
        weights: dict[str, float] = {}
        for dimension in cls.functional_dimensions:
            requested = dimension_fields.get(dimension, "")
            normalized_requested = CMDBParserService.normalize_header(requested)
            source_field = next(
                (
                    column
                    for column in text_columns
                    if CMDBParserService.normalize_header(column)
                    == normalized_requested
                ),
                None,
            )
            if source_field is None:
                raise SimilarityPrerequisiteError(
                    f"Configured {cls.field_labels[dimension]} field '{requested}' is not available in the current CMDB"
                )
            if normalized_requested in {
                CMDBParserService.normalize_header(alias)
                for alias in cls.field_aliases["portfolio"]
            }:
                raise SimilarityPrerequisiteError(
                    "Portfolio is contextual metadata and cannot be used as functional similarity evidence"
                )
            resolved[dimension] = source_field
            raw_weight = (dimension_weights or {}).get(dimension, 1.0)
            if (
                isinstance(raw_weight, bool)
                or not isinstance(raw_weight, (int, float))
                or not isfinite(float(raw_weight))
                or float(raw_weight) < 0
            ):
                raise SimilarityPrerequisiteError(
                    f"Similarity weight for {cls.field_labels[dimension]} must be a non-negative number"
                )
            weights[dimension] = float(raw_weight)
        total = sum(weights.values())
        if not total:
            raise SimilarityPrerequisiteError(
                "At least one functional similarity weight must be greater than zero"
            )
        return (
            list(cls.functional_dimensions),
            {key: round(value / total * 100, 6) for key, value in weights.items()},
            resolved,
        )

    @classmethod
    def _resolve_requested_field(
        cls, requested: Any, columns: Iterable[str]
    ) -> str | None:
        canonical = cls._canonical_field(requested)
        if canonical is not None:
            return canonical
        normalized = CMDBParserService.normalize_header(str(requested))
        return next(
            (
                column
                for column in columns
                if CMDBParserService.normalize_header(column) == normalized
            ),
            None,
        )

    @classmethod
    def _canonical_field(cls, requested: Any) -> str | None:
        normalized = CMDBParserService.normalize_header(str(requested))
        aliases: dict[str, tuple[str, ...]] = {
            "name": ("name", *CMDBParserService.application_name_aliases),
            "description": ("description", *cls.field_aliases["description"]),
            "portfolio": ("portfolio", *cls.field_aliases["portfolio"]),
            "technology_stack": (
                "technology_stack",
                *cls.field_aliases["technology_stack"],
            ),
            "application_technology": (
                "application_technology",
                *cls.field_aliases["application_technology"],
            ),
            "platform_hosting": (
                "platform_hosting",
                "Platform / Hosting",
                *cls.field_aliases["platform"],
                *cls.field_aliases["hosting_type"],
                *cls.field_aliases["hosting_provider"],
            ),
            "department": ("department", *cls.field_aliases["department"]),
            "app_classification": (
                "app_classification",
                *cls.field_aliases["app_classification"],
            ),
        }
        for field, names in aliases.items():
            if any(
                normalized == CMDBParserService.normalize_header(name)
                for name in names
            ):
                return field
        return None

    def _analysis_warnings(
        self,
        job_id: str,
        upload_id: str,
        preview: dict[str, Any],
        applications: list[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        validation_path = f"jobs/{job_id}/results/cmdb_validation.json"
        validation_current = False
        if self.storage.exists(validation_path):
            validation = self.storage.load_json(validation_path)
            validation_current = validation.get("upload_id") == upload_id
        if not validation_current:
            warnings.append(
                "CMDB validation has not been run for the latest parsed upload; similarity used the parsed CMDB preview directly."
            )
        if not preview.get("application_code_column"):
            warnings.append(
                "Application Code was not found; response application code fields are empty."
            )
        if not applications:
            warnings.append("The parsed CMDB preview contains no applications to compare.")
        return warnings

    @classmethod
    def _resolve_columns(cls, columns: Iterable[Any]) -> dict[str, str | None]:
        text_columns = [str(column) for column in columns]
        by_normalized = {
            CMDBParserService.normalize_header(column): column for column in text_columns
        }
        resolved: dict[str, str | None] = {}
        for field, aliases in cls.field_aliases.items():
            resolved[field] = next(
                (
                    by_normalized[CMDBParserService.normalize_header(alias)]
                    for alias in aliases
                    if CMDBParserService.normalize_header(alias) in by_normalized
                ),
                None,
            )
        return resolved

    @classmethod
    def _prepare_record(
        cls,
        record: dict[str, Any],
        preview: dict[str, Any],
        resolved: dict[str, str | None],
        dimension_fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        source = record.get("source_data", {})
        code_column = preview.get("application_code_column") or preview.get(
            "application_id_column"
        )
        name_column = preview.get("application_name_column")
        code = cls._display(source.get(code_column)) if code_column else ""
        name = cls._display(source.get(name_column)) if name_column else ""
        fallback_key = cls._display(record.get("application_key"))
        fallback_name = cls._display(record.get("application_name"))
        values = {}
        for field, column in resolved.items():
            value = cls._display(source.get(column)) if column else ""
            values[field] = "" if cls._is_placeholder(value) else value
        for column, raw_value in source.items():
            value = cls._display(raw_value)
            values.setdefault(
                str(column), "" if cls._is_placeholder(value) else value
            )
        values["name"] = "" if cls._is_placeholder(name) else name
        values["platform_hosting"] = " ".join(
            value
            for value in (
                values.get("platform", ""),
                values.get("hosting_type", ""),
                values.get("hosting_provider", ""),
            )
            if value
        )
        for dimension, source_field in (dimension_fields or {}).items():
            values[dimension] = values.get(source_field, "")
        return {
            "code": code,
            "primary_code": code,
            "name": name,
            "comparison_name": name,
            "effective_identity": code or fallback_key or fallback_name,
            "values": values,
            "normalized": {
                field: cls._meaningful_text(value) for field, value in values.items()
            },
            "tokens": {
                field: cls._tokens(value) for field, value in values.items()
            },
            "row": record.get("internal_row_number"),
        }

    @classmethod
    def _candidate_pairs(
        cls,
        applications: list[dict[str, Any]],
        selected_fields: Iterable[str] | None = None,
        weights: dict[str, float] | None = None,
        minimum_score: float = 0,
        *,
        postings: dict[str, dict[str, list[int]]] | None = None,
    ) -> Iterable[tuple[int, int]]:
        # With exact-or-Jaccard scoring, a positive component requires at least
        # one shared normalized token. The inverted index therefore omits only
        # pairs whose mathematically possible score is zero; it is exact, not
        # approximate candidate generation.
        if postings is None:
            postings = cls._candidate_postings(
                applications, selected_fields or (), weights
            )
        candidates: set[tuple[int, int]] = set()
        for field_postings in postings.values():
            for indexes in field_postings.values():
                candidates.update(combinations(indexes, 2))
        if minimum_score <= 0 or weights is None:
            return sorted(candidates)
        qualifying = []
        for left_index, right_index in candidates:
            left = applications[left_index]
            right = applications[right_index]
            possible_score = 0.0
            for field in selected_fields or ():
                left_normalized = left["normalized"].get(field, "")
                right_normalized = right["normalized"].get(field, "")
                if not left_normalized or not right_normalized:
                    continue
                possible_score += weights.get(field, 0.0) * (
                    1.0
                    if left_normalized == right_normalized
                    else cls._jaccard(
                        left["tokens"].get(field, set()),
                        right["tokens"].get(field, set()),
                    )
                )
            if possible_score + 1e-9 >= minimum_score:
                qualifying.append((left_index, right_index))
        return sorted(qualifying)

    @staticmethod
    def _candidate_postings(
        applications: list[dict[str, Any]],
        selected_fields: Iterable[str],
        weights: dict[str, float] | None,
    ) -> dict[str, dict[str, list[int]]]:
        postings: dict[str, dict[str, list[int]]] = {}
        for index, application in enumerate(applications):
            for field in selected_fields:
                if weights is not None and weights.get(field, 0) <= 0:
                    continue
                field_postings = postings.setdefault(field, {})
                for token in application["tokens"].get(field, set()):
                    field_postings.setdefault(token, []).append(index)
        return postings

    @classmethod
    def _deduplicate_applications(
        cls, applications: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[tuple[str, ...]] = set()
        for application in applications:
            code = cls._normalize_text(application["primary_code"])
            if code:
                identity = ("code", code)
            else:
                identity = (
                    "fallback",
                    cls._normalize_text(application["effective_identity"]),
                    cls._normalize_text(application["name"]),
                )
            if identity not in seen:
                seen.add(identity)
                unique.append(application)
        return unique

    @classmethod
    def _serializable_application(
        cls, application: dict[str, Any], index: int
    ) -> dict[str, Any]:
        portfolio = application["values"].get("portfolio", "")
        return {
            "application_key": f"app-{index}",
            "code": application["code"],
            "primary_code": application["primary_code"],
            "name": application["name"],
            "comparison_name": application["comparison_name"],
            "effective_identity": application["effective_identity"],
            "values": application["values"],
            "normalized": application["normalized"],
            "tokens": {
                field: sorted(tokens)
                for field, tokens in application["tokens"].items()
            },
            "portfolio": portfolio,
            "normalized_code": cls._normalize_text(application["code"]),
            "normalized_name": cls._normalize_text(application["name"]),
            "normalized_portfolio": cls._normalize_text(portfolio),
            "row": application.get("row"),
        }

    @classmethod
    def _state_applications(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        applications = result.get("analysis_state", {}).get("applications", [])
        hydrated = []
        for application in applications:
            item = dict(application)
            item["tokens"] = {
                field: set(tokens)
                for field, tokens in application.get("tokens", {}).items()
            }
            hydrated.append(item)
        return hydrated

    @classmethod
    def _portfolio_field(cls, columns: Iterable[Any]) -> str:
        normalized_portfolio = CMDBParserService.normalize_header("Portfolio")
        return next(
            (
                str(column)
                for column in columns
                if CMDBParserService.normalize_header(str(column))
                == normalized_portfolio
            ),
            "",
        )

    @classmethod
    def _similar_apps_group(
        cls,
        selected_index: int,
        applications: list[dict[str, Any]],
        result: dict[str, Any],
        limit: int,
        normalized_portfolio: str = "",
        excluded_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        rules = result["rules_config"]
        selected = applications[selected_index]
        heap: list[tuple[float, int, dict[str, Any]]] = []
        order = 0
        for index, other in enumerate(applications):
            if (
                index == selected_index
                or other["application_key"] in (excluded_keys or set())
                or (
                    normalized_portfolio
                    and other["normalized_portfolio"] != normalized_portfolio
                )
            ):
                continue
            pair = cls._score_pair(
                selected,
                other,
                float(rules["possible_duplicate_threshold"]),
                list(rules["selected_fields_used"]),
                dict(rules["field_weights_used"]),
            )
            if pair.pop("comparable_dimension_count") == 0:
                continue
            cls._push_bounded(
                heap, cls._similar_application(pair, "b"), limit, order
            )
            order += 1
        similar = cls._sorted_heap(heap)
        return {
            "application_code": selected["code"],
            "application_name": selected["name"],
            "similar_applications": similar,
            "highest_similarity_score": (
                similar[0]["similarity_score"] if similar else None
            ),
            "possible_duplicate_count": sum(
                int(item["possible_duplicate"]) for item in similar
            ),
            "warning_count": sum(
                int(not item["possible_duplicate"]) for item in similar
            ),
        }

    @classmethod
    def _score_pair(
        cls,
        left: dict[str, Any],
        right: dict[str, Any],
        duplicate_threshold: float,
        selected_fields: list[str],
        weights: dict[str, float],
    ) -> dict[str, Any]:
        components: list[tuple[str, float, float]] = []
        evidence: list[str] = []
        matched_fields: list[str] = []
        differing_fields: list[str] = []
        missing_fields: list[str] = []
        component_details: dict[str, dict[str, Any]] = {}
        for field in selected_fields:
            weight = weights.get(field, 0.0)
            left_normalized = left["normalized"].get(field, "")
            right_normalized = right["normalized"].get(field, "")
            if not left_normalized or not right_normalized:
                label = cls.field_labels.get(field, field)
                missing_fields.append(label)
                if not left_normalized and not right_normalized:
                    reason = f"{label} metadata missing for both applications"
                else:
                    reason = f"{label} metadata missing for one application"
                component_details[field] = {
                    "score": None,
                    "comparable": False,
                    "reason": reason,
                    "evidence": [],
                }
                continue
            left_tokens = left["tokens"].get(field, set())
            right_tokens = right["tokens"].get(field, set())
            value = (
                1.0
                if left_normalized == right_normalized
                else cls._jaccard(left_tokens, right_tokens)
            )
            components.append((field, value, weight))
            label = cls.field_labels.get(field, field)
            shared = sorted(left_tokens & right_tokens)
            compared_evidence = [
                f"Application A: {left['values'].get(field, '')}",
                f"Application B: {right['values'].get(field, '')}",
            ]
            if shared:
                compared_evidence.append(f"Shared terms: {', '.join(shared)}")
            if value > 0:
                matched_fields.append(label)
                if value == 1:
                    evidence.append(f"Exact normalized {label} match")
                else:
                    evidence.append(f"{label} token overlap: {', '.join(shared)}")
            else:
                differing_fields.append(label)
            component_details[field] = {
                "score": round(value * 100, 2),
                "comparable": True,
                "reason": (
                    f"Shared normalized {label} evidence"
                    if value > 0
                    else f"No overlapping normalized {label} terms"
                ),
                "evidence": compared_evidence,
            }

        # Pair-specific effective weights preserve the configured proportions
        # while excluding missing dimensions. For comparable dimensions C:
        # effective_weight_i = configured_weight_i / sum(weight_j for j in C).
        # This prevents unavailable metadata from being silently scored as 0%.
        comparable_weight = sum(weight for _, _, weight in components)
        weighted_score = (
            sum(value * weight for _, value, weight in components)
            / comparable_weight
            * 100
            if comparable_weight
            else 0.0
        )
        component_scores: dict[str, float | None] = {
            field: None for field in selected_fields
        }
        for field, value, _ in components:
            component_scores[field] = round(value * 100, 2)
        score = round(weighted_score, 2)
        contributing = sorted(
            (
                (value * weight, cls.field_labels.get(field, field), sorted(left["tokens"].get(field, set()) & right["tokens"].get(field, set())))
                for field, value, weight in components
                if value > 0 and weight > 0
            ),
            key=lambda item: (-item[0], item[1].casefold()),
        )
        if contributing:
            primary = contributing[:2]
            explanations = []
            for _, label, shared_terms in primary:
                term_note = f" (shared terms: {', '.join(shared_terms[:5])})" if shared_terms else " (normalized values match)"
                explanations.append(f"{label}{term_note}")
            similarity_reason = "Similarity reflects " + " and ".join(explanations) + "."
        elif components:
            similarity_reason = (
                "Comparable metadata was found, but no normalized terms overlapped."
            )
        else:
            similarity_reason = "The applications do not have comparable metadata."
        return {
            "application_code_a": left["code"],
            "application_name_a": left["name"],
            "application_code_b": right["code"],
            "application_name_b": right["name"],
            "similarity_score": score,
            "possible_duplicate": score >= duplicate_threshold,
            "evidence": evidence,
            "matched_fields": list(dict.fromkeys(matched_fields)),
            "differing_fields": differing_fields,
            "missing_fields": list(dict.fromkeys(missing_fields)),
            "component_scores": component_scores,
            "component_details": component_details,
            "similarity_reason": similarity_reason,
            "comparable_dimension_count": sum(
                1 for _, _, weight in components if weight > 0
            ),
        }

    @classmethod
    def _comparison_application(cls, application: dict[str, Any]) -> dict[str, Any]:
        key_fields = {"Application Name": application["name"]}
        for field, label in (
            ("description", "Description"),
            ("portfolio", "Portfolio"),
            ("technology_stack", "Technology Stack"),
            ("application_technology", "Application Technology"),
            ("platform", "Platform"),
            ("hosting_type", "Hosting Type"),
            ("hosting_provider", "Hosting Provider"),
            ("department", "Department"),
            ("app_classification", "App Classification"),
        ):
            value = application["values"][field]
            if value:
                key_fields[label] = value
        return {
            "application_code": application["code"],
            "application_name": application["name"],
            "key_fields": key_fields,
        }

    @staticmethod
    def _recommendation(possible_duplicate: bool) -> str:
        if possible_duplicate:
            return "Confirm whether these applications are duplicates or separate regional/business variants."
        return "Review ownership, purpose, and usage before rationalization."

    @classmethod
    def _stored_pair_is_self(cls, pair: dict[str, Any]) -> bool:
        code_a = cls._normalize_text(str(pair.get("application_code_a", "")))
        code_b = cls._normalize_text(str(pair.get("application_code_b", "")))
        if code_a and code_b:
            return code_a == code_b
        return bool(
            cls._normalize_text(str(pair.get("application_name_a", "")))
            == cls._normalize_text(str(pair.get("application_name_b", "")))
        )

    @staticmethod
    def _push_bounded(
        heap: list[tuple[float, int, dict[str, Any]]],
        record: dict[str, Any],
        limit: int,
        order: int,
    ) -> None:
        item = (float(record["similarity_score"]), -order, record)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)

    @staticmethod
    def _sorted_heap(
        heap: list[tuple[float, int, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        return [
            item[2]
            for item in sorted(heap, key=lambda item: (-item[0], -item[1]))
        ]

    @staticmethod
    def _similar_application(
        pair: dict[str, Any], other_side: str
    ) -> dict[str, Any]:
        return {
            "application_code": pair[f"application_code_{other_side}"],
            "application_name": pair[f"application_name_{other_side}"],
            "similarity_score": pair["similarity_score"],
            "possible_duplicate": pair["possible_duplicate"],
            "evidence": pair.get("evidence", []),
            "matched_fields": pair.get("matched_fields", []),
            "component_scores": pair.get("component_scores", {}),
            "component_details": pair.get("component_details", {}),
            "similarity_reason": pair.get("similarity_reason", ""),
        }

    @classmethod
    def _group_application_heaps(
        cls,
        heaps: list[list[tuple[float, int, dict[str, Any]]]],
        applications: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for application, heap in zip(applications, heaps):
            similar = cls._sorted_heap(heap)
            groups.append(
                {
                    "application_code": application["code"],
                    "application_name": application["name"],
                    "similar_applications": similar,
                    "highest_similarity_score": (
                        similar[0]["similarity_score"] if similar else None
                    ),
                    "possible_duplicate_count": sum(
                        int(item["possible_duplicate"]) for item in similar
                    ),
                    "warning_count": sum(
                        int(not item["possible_duplicate"]) for item in similar
                    ),
                }
            )
        return groups

    @staticmethod
    def _application_reference(
        application: dict[str, Any], strongest_score: float | None = None
    ) -> dict[str, Any]:
        return {
            "application_key": application.get("application_key", ""),
            "application_code": application["code"],
            "application_name": application["name"],
            "portfolio": application.get("portfolio", ""),
            "strongest_similarity_score": strongest_score,
        }

    @classmethod
    def _build_clusters(
        cls,
        accumulator: _ClusterAccumulator,
        applications: list[dict[str, Any]],
        selected_fields: list[str],
    ) -> list[dict[str, Any]]:
        members: dict[int, list[int]] = {}
        for index in range(len(applications)):
            root = accumulator.find(index)
            members.setdefault(root, []).append(index)
        connected = [indexes for indexes in members.values() if len(indexes) > 1]
        connected.sort(
            key=lambda indexes: (
                -len(indexes),
                cls._normalize_text(applications[indexes[0]]["code"]),
                cls._normalize_text(applications[indexes[0]]["name"]),
            )
        )
        clusters = []
        for number, indexes in enumerate(connected, start=1):
            root = accumulator.find(indexes[0])
            count = accumulator.edge_count[root]
            cluster_applications = [applications[index] for index in indexes]
            common_function, cluster_evidence = cls._cluster_common_evidence(
                cluster_applications, selected_fields
            )
            clusters.append(
                {
                    "cluster": f"Cluster {number}",
                    "application_count": len(indexes),
                    "applications": [
                        cls._application_reference(applications[index])
                        for index in indexes
                    ],
                    "average_similarity": round(
                        accumulator.score_sum[root] / count if count else 0.0, 2
                    ),
                    "common_cluster_function": common_function,
                    "evidence_used_for_analysis": cluster_evidence,
                    "cluster_reason": (
                        f"Grouped because all {len(indexes)} applications share {cluster_evidence}. "
                        f"The group is connected by {count} qualifying pair comparisons at an average similarity of "
                        f"{(accumulator.score_sum[root] / count if count else 0.0):.2f}%."
                        if cluster_evidence != "Not established from available metadata"
                        else f"Grouped by qualifying pair similarity links, but the configured metadata does not establish one shared function across all {len(indexes)} applications."
                    ),
                    "comparable_dimension_count": (
                        round(accumulator.comparable_dimension_sum[root] / count)
                        if count
                        else 0
                    ),
                    "average_calculation": (
                        f"{round(accumulator.score_sum[root] / count, 2):.2f}% is the mean of {count} qualifying pair score(s); "
                        f"each pair was averaged across its comparable functional dimensions only."
                    ),
                }
            )
        return clusters

    @classmethod
    def _cluster_common_evidence(
        cls,
        applications: list[dict[str, Any]],
        selected_fields: list[str],
    ) -> tuple[str, str]:
        by_label = {
            CMDBParserService.normalize_header(cls.field_labels.get(field, field)): field
            for field in selected_fields
        }
        evidence: list[tuple[str, str]] = []
        for label in cls.cluster_evidence_priority:
            field = by_label.get(CMDBParserService.normalize_header(label))
            if field is None:
                continue
            token_sets = [app["tokens"].get(field, set()) for app in applications]
            if not token_sets or any(not tokens for tokens in token_sets):
                continue
            shared = set.intersection(*token_sets)
            if not shared:
                continue
            normalized_values = [app["normalized"].get(field, "") for app in applications]
            if len(set(normalized_values)) == 1:
                display = applications[0]["values"].get(field, "") or " ".join(sorted(shared))
            else:
                display = " ".join(sorted(shared)).title()
            evidence.append((label, display))
        if not evidence:
            missing = "Not established from available metadata"
            return missing, missing
        return evidence[0][1], "; ".join(
            f"{label}: {value}" for label, value in evidence
        )

    @staticmethod
    def _display(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))

    @staticmethod
    def _score_range(value: str) -> tuple[int, int]:
        if value in {"0-100", "50-100"}:
            return tuple(map(int, value.split("-")))
        if value == "20-100":
            return 20, 100
        match = re.fullmatch(r"(\d{1,3})-(\d{1,3})", value.strip())
        if not match:
            raise SimilarityPrerequisiteError("Select a valid similarity score range")
        lower, upper = (int(match.group(1)), int(match.group(2)))
        valid = {(0, 10), *((start, min(start + 9, 100)) for start in range(11, 101, 10))}
        if (lower, upper) not in valid:
            raise SimilarityPrerequisiteError("Select a valid similarity score range")
        return lower, upper

    @staticmethod
    def _score_in_range(score: float, score_range: tuple[int, int]) -> bool:
        rounded = CMDBSimilarityService._displayed_score(score)
        return score_range[0] <= rounded <= score_range[1]

    @staticmethod
    def _displayed_score(score: float) -> int:
        return min(100, max(0, floor(float(score) + 0.5)))

    @staticmethod
    def _score_range_note(value: str) -> str:
        if value == "50-100":
            return "Showing matches with displayed scores of 50% or higher."
        if value == "0-100":
            return "Showing matches across all displayed similarity scores from 0% through 100%."
        if value == "20-100":
            return "Showing matches with displayed scores of 20% or higher."
        return (
            "Score bands use the score rounded to the nearest whole percent; "
            "for example, 10.50% appears in the 11–20% band."
        )

    @classmethod
    def _is_placeholder(cls, value: str) -> bool:
        normalized = cls._normalize_text(value)
        return (
            not normalized
            or normalized in cls.placeholder_values
            or not cls._meaningful_text(value)
        )

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return set(cls._meaningful_text(value).split()) if value else set()

    @classmethod
    def _meaningful_text(cls, value: str) -> str:
        return " ".join(
            token
            for token in cls._normalize_text(value).split()
            if token not in cls.overlap_stop_words
        )

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    @classmethod
    def _same_effective_identity(
        cls, left: dict[str, Any], right: dict[str, Any]
    ) -> bool:
        left_code = cls._normalize_text(left["primary_code"])
        right_code = cls._normalize_text(right["primary_code"])
        if left_code and right_code:
            return left_code == right_code

        same_identity = cls._normalize_text(
            left["effective_identity"]
        ) == cls._normalize_text(right["effective_identity"])
        same_name = cls._normalize_text(left["name"]) == cls._normalize_text(
            right["name"]
        )
        return bool(same_identity and same_name)

    def _result_path(self, job_id: str) -> str:
        return f"jobs/{job_id}/results/{self.result_file_name}"
