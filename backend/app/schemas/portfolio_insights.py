from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiSchema, ResponseStatus


RiskSeverity = Literal["low", "medium", "high", "critical"]
ModuleAvailability = Literal["available", "missing", "error"]


class PortfolioInsightsRequest(ApiSchema):
    risk_limit: int = Field(default=100, ge=1, le=5_000)
    action_limit: int = Field(default=100, ge=1, le=5_000)
    portfolio_limit: int = Field(default=100, ge=1, le=500)
    include_low_severity: bool = True


class ModuleStatusRecord(ApiSchema):
    module_name: str
    status: ModuleAvailability
    analysis_status: str | None = None
    source_result_available: bool
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RiskRecord(ApiSchema):
    risk_id: str
    risk_type: Literal[
        "cmdb_missing_mandatory_data",
        "duplicate_application_code",
        "possible_duplicate_application",
        "obsolete_technology_indicator",
        "explicit_integration_with_unknown_target",
        "output_family_unmapped_application",
        "output_family_config_member_not_found",
        "output_family_ambiguous_member",
        "output_family_without_members",
        "missing_portfolio",
        "missing_business_criticality",
    ]
    severity: RiskSeverity
    application_code: str | None = None
    application_name: str | None = None
    portfolio: str | None = None
    evidence_module: str
    evidence: str
    recommended_action: str
    confidence: Literal["low", "medium", "high"]


class ActionItemRecord(ApiSchema):
    action_id: str
    priority: RiskSeverity
    action_type: str
    application_code: str | None = None
    application_name: str | None = None
    portfolio: str | None = None
    description: str
    source_risk_id: str
    owner_hint: str | None = None
    evidence_module: str


class PortfolioScorecardRecord(ApiSchema):
    portfolio: str
    application_count: int
    completeness_percent: float | None = None
    critical_application_count: int
    high_business_criticality_count: int
    possible_duplicate_count: int | None = None
    obsolete_indicator_count: int | None = None
    explicit_integration_count: int | None = None
    unmapped_output_family_application_count: int | None = None
    risk_count: int
    highest_risk_severity: RiskSeverity | None = None
    warnings: list[str] = Field(default_factory=list)


class ExecutiveSummary(ApiSchema):
    total_applications: int
    cmdb_completeness_percent: float | None = None
    source_of_truth_label: str
    reliability_label: str
    high_priority_risk_count: int
    medium_priority_risk_count: int
    low_priority_risk_count: int
    possible_duplicate_count: int | None = None
    technology_obsolete_indicator_count: int | None = None
    explicit_integration_count: int | None = None
    output_family_warning_count: int | None = None
    unmapped_output_family_application_count: int | None = None
    key_findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PortfolioInsightsSummary(ApiSchema):
    total_applications: int
    total_portfolios: int
    available_module_count: int
    missing_module_count: int
    total_risk_count: int
    critical_risk_count: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    action_item_count: int
    source_of_truth_label: str
    reliability_label: str
    warning_count: int


class PortfolioInsightsDetailEndpoints(ApiSchema):
    summary_endpoint: str
    executive_summary_endpoint: str
    module_status_endpoint: str
    portfolio_scorecard_endpoint: str
    risks_endpoint: str
    action_items_endpoint: str
    application_insight_endpoint_template: str
    risks_csv_endpoint: str
    action_items_csv_endpoint: str
    portfolio_scorecard_csv_endpoint: str


class PortfolioInsightsResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["portfolio_insights"] = "portfolio_insights"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: PortfolioInsightsSummary
    executive_summary: ExecutiveSummary
    module_status: list[ModuleStatusRecord] = Field(default_factory=list)
    top_portfolio_scorecards: list[PortfolioScorecardRecord] = Field(
        default_factory=list
    )
    risk_sample: list[RiskRecord] = Field(default_factory=list)
    action_item_sample: list[ActionItemRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    detail_endpoints: PortfolioInsightsDetailEndpoints


class PortfolioInsightsSummaryResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["portfolio_insights"] = "portfolio_insights"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: PortfolioInsightsSummary
    warnings: list[str] = Field(default_factory=list)


class ExecutiveSummaryResponse(ApiSchema):
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    executive_summary: ExecutiveSummary
    warnings: list[str] = Field(default_factory=list)


class ModuleStatusResponse(ApiSchema):
    job_id: str
    upload_id: str
    modules: list[ModuleStatusRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PortfolioScorecardResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_portfolio_count: int
    portfolios: list[PortfolioScorecardRecord] = Field(default_factory=list)


class RiskRegisterResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_risk_count: int
    risks: list[RiskRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ActionItemsResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_action_item_count: int
    action_items: list[ActionItemRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplicationIdentity(ApiSchema):
    application_code: str
    application_name: str | None = None
    portfolio: str | None = None
    business_criticality: str | None = None
    status: str | None = None
    operational_status: str | None = None
    support_owner: str | None = None
    tech_product_owner: str | None = None
    business_product_owner: str | None = None


class ApplicationInsightResponse(ApiSchema):
    job_id: str
    upload_id: str
    application: ApplicationIdentity
    validation_insights: dict[str, Any] | None = None
    similarity_insights: list[dict[str, Any]] | None = None
    technology_insights: dict[str, Any] | None = None
    output_family_insights: dict[str, Any] | None = None
    risks: list[RiskRecord] = Field(default_factory=list)
    action_items: list[ActionItemRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
