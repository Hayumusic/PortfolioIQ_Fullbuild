from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiSchema, ResponseStatus


class SimilarityAnalysisRequest(ApiSchema):
    similar_pair_threshold: float = Field(default=60, ge=0, le=100)
    possible_duplicate_threshold: float = Field(default=85, ge=0, le=100)
    max_pairs: int = Field(default=200, ge=1, le=1_000)
    per_application_limit: int = Field(default=10, ge=1, le=50)
    selected_fields: list[str] | None = None
    field_weights: dict[str, Any] | None = None
    dimension_fields: dict[str, str] | None = None
    dimension_weights: dict[str, Any] | None = None
    # Retained as an optional compatibility input. The UI does not expose it;
    # new analyses use the service's internal clustering rule.
    cluster_threshold: float | None = Field(default=None, ge=0, le=100)
    heatmap_limit: int = Field(default=50, ge=1, le=100)
    alert_limit: int = Field(default=200, ge=1, le=200)

    @model_validator(mode="after")
    def duplicate_threshold_is_not_lower(self) -> "SimilarityAnalysisRequest":
        if self.possible_duplicate_threshold < self.similar_pair_threshold:
            raise ValueError(
                "possible_duplicate_threshold must be greater than or equal to similar_pair_threshold"
            )
        return self


class SimilaritySummary(ApiSchema):
    total_applications_analyzed: int
    total_candidate_pairs_evaluated: int
    analysis_elapsed_seconds: float
    similar_pair_count: int
    possible_duplicate_count: int
    similar_pair_threshold: float
    possible_duplicate_threshold: float
    source_of_truth_label: str
    reliability_label: str
    warning_count: int


class SimilarityRulesConfig(ApiSchema):
    scoring_method: Literal["deterministic"] = "deterministic"
    selected_fields_used: list[str] = Field(default_factory=list)
    field_weights_used: dict[str, float] = Field(default_factory=dict)
    dimension_fields_used: dict[str, str] = Field(default_factory=dict)
    cluster_threshold: float = 60
    similar_pair_threshold: float
    possible_duplicate_threshold: float
    max_pairs: int
    per_application_limit: int
    heatmap_limit: int
    alert_limit: int
    stop_words_applied: bool
    evidence_rules: list[str] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SimilarityDimensionComparison(ApiSchema):
    score: float | None = None
    comparable: bool
    reason: str
    evidence: list[str] = Field(default_factory=list)


class SimilarPair(ApiSchema):
    application_code_a: str
    application_name_a: str
    application_code_b: str
    application_name_b: str
    similarity_score: float
    possible_duplicate: bool
    evidence: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    differing_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    component_scores: dict[str, float | None] = Field(default_factory=dict)
    component_details: dict[str, SimilarityDimensionComparison] = Field(
        default_factory=dict
    )
    similarity_reason: str = ""


class SimilarApplication(ApiSchema):
    application_code: str
    application_name: str
    similarity_score: float
    possible_duplicate: bool
    evidence: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    component_scores: dict[str, float | None] = Field(default_factory=dict)
    component_details: dict[str, SimilarityDimensionComparison] = Field(
        default_factory=dict
    )
    similarity_reason: str = ""


class SimilarAppsGroup(ApiSchema):
    application_code: str
    application_name: str
    similar_applications: list[SimilarApplication] = Field(default_factory=list)
    highest_similarity_score: float | None = None
    possible_duplicate_count: int = 0
    warning_count: int = 0


class SimilarityOverviewResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["similarity"] = "similarity"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: SimilaritySummary
    top_similar_pairs: list[SimilarPair] = Field(default_factory=list)
    selected_fields_used: list[str] = Field(default_factory=list)
    field_weights_used: dict[str, float] = Field(default_factory=dict)
    unsupported_fields: list[str] = Field(default_factory=list)
    rules_config: SimilarityRulesConfig
    warnings: list[str] = Field(default_factory=list)
    summary_endpoint: str
    pairs_endpoint: str
    apps_endpoint: str
    rules_endpoint: str
    heatmap_endpoint: str
    alerts_endpoint: str
    clusters_endpoint: str
    compare_endpoint: str
    csv_endpoint: str
    detail_endpoints: dict[str, str] = Field(default_factory=dict)


class SimilaritySummaryResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["similarity"] = "similarity"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: SimilaritySummary
    warnings: list[str] = Field(default_factory=list)


class SimilarityPairsResponse(ApiSchema):
    job_id: str
    upload_id: str
    page: int
    page_size: int
    total_records: int
    total_pages: int
    records: list[SimilarPair] = Field(default_factory=list)


class SimilarityAppsResponse(ApiSchema):
    job_id: str
    upload_id: str
    per_application_limit: int
    applications: list[SimilarAppsGroup] = Field(default_factory=list)


class SimilarityRulesResponse(ApiSchema):
    job_id: str
    upload_id: str
    rules_config: SimilarityRulesConfig
    applications: list["HeatmapApplication"] = Field(default_factory=list)
    portfolio_options: list[str] = Field(default_factory=list)


class HeatmapApplication(ApiSchema):
    application_key: str = ""
    application_code: str
    application_name: str
    portfolio: str = ""
    strongest_similarity_score: float | None = None


class HeatmapCell(ApiSchema):
    anchor_application_key: str
    anchor_application_code: str
    anchor_application_name: str
    candidate_application_key: str
    candidate_application_code: str
    candidate_application_name: str
    candidate_portfolio: str = ""
    similarity_score: float
    possible_duplicate: bool


class SimilarityHeatmapResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    matched_anchor_count: int = 0
    candidate_count: int = 0
    no_comparable_data: bool = False
    portfolio_options: list[str] = Field(default_factory=list)
    anchor_applications: list[HeatmapApplication] = Field(default_factory=list)
    candidate_applications: list[HeatmapApplication] = Field(default_factory=list)
    matrix: list[HeatmapCell] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score_range: str = "20-100"
    score_range_note: str = ""


class SimilarityCluster(ApiSchema):
    cluster: str
    application_count: int
    applications: list[HeatmapApplication] = Field(default_factory=list)
    average_similarity: float
    common_cluster_function: str
    evidence_used_for_analysis: str
    cluster_reason: str = ""
    comparable_dimension_count: int = 0
    average_calculation: str = ""


class SimilarityClustersResponse(ApiSchema):
    job_id: str
    upload_id: str
    clusters: list[SimilarityCluster] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RedundancyAlert(ApiSchema):
    alert_type: Literal["possible_duplicate", "high_similarity"]
    severity: Literal["warning", "critical"]
    application_code_a: str
    application_name_a: str
    application_code_b: str
    application_name_b: str
    application_key_a: str = ""
    application_key_b: str = ""
    portfolio_a: str = ""
    portfolio_b: str = ""
    similarity_score: float
    evidence: list[str] = Field(default_factory=list)
    recommendation: str
    matched_fields: list[str] = Field(default_factory=list)
    redundancy_reason: str = ""
    component_details: dict[str, SimilarityDimensionComparison] = Field(
        default_factory=dict
    )


class SimilarityAlertsResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_alert_count: int
    alerts: list[RedundancyAlert] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComparisonApplication(ApiSchema):
    application_code: str
    application_name: str
    key_fields: dict[str, str] = Field(default_factory=dict)


class SimilarityComparisonResponse(ApiSchema):
    job_id: str
    upload_id: str
    application_a: ComparisonApplication
    application_b: ComparisonApplication
    similarity_score: float | None = None
    possible_duplicate: bool
    evidence: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    differing_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    recommendation: str
    from_stored_result: bool
