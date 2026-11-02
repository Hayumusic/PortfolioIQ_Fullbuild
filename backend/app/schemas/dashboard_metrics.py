from typing import Literal

from pydantic import Field

from app.schemas.cmdb import MandatoryColumnMatch
from app.schemas.common import ApiSchema, ResponseStatus
from app.schemas.similarity import SimilarPair


class DashboardMetricsRequest(ApiSchema):
    top_n: int = Field(default=10, ge=1, le=100)
    include_similarity: bool = True


class DashboardOverview(ApiSchema):
    total_applications: int
    total_columns: int
    source_of_truth_label: str
    reliability_label: str
    overall_completeness: float | None = None
    warning_count: int


class DashboardCard(ApiSchema):
    key: str
    label: str
    value: str | int | float | None
    severity: Literal["info", "success", "warning", "critical"]
    description: str


class CountedValue(ApiSchema):
    value: str
    count: int


class ApplicationStatusDistribution(ApiSchema):
    status_counts: dict[str, int] = Field(default_factory=dict)
    operational_status_counts: dict[str, int] = Field(default_factory=dict)


class PortfolioDistribution(ApiSchema):
    counts: dict[str, int] = Field(default_factory=dict)
    top_portfolios: list[CountedValue] = Field(default_factory=list)
    missing_portfolio_count: int


class BusinessCriticalityDistribution(ApiSchema):
    counts: dict[str, int] = Field(default_factory=dict)
    missing_criticality_count: int


class HostingDistribution(ApiSchema):
    hosting_type_counts: dict[str, int] = Field(default_factory=dict)
    hosting_provider_counts: dict[str, int] = Field(default_factory=dict)
    missing_hosting_type_count: int
    missing_hosting_provider_count: int


class TechnologyDistribution(ApiSchema):
    top_technology_stack: list[CountedValue] = Field(default_factory=list)
    top_application_technology: list[CountedValue] = Field(default_factory=list)
    top_platforms: list[CountedValue] = Field(default_factory=list)
    missing_technology_count: int


class SecurityAccessDistribution(ApiSchema):
    user_authentication_counts: dict[str, int] = Field(default_factory=dict)
    mfa_counts: dict[str, int] = Field(default_factory=dict)
    waf_counts: dict[str, int] = Field(default_factory=dict)
    missing_user_authentication_count: int
    missing_mfa_count: int
    missing_waf_count: int


class DashboardDistributions(ApiSchema):
    application_status: ApplicationStatusDistribution
    portfolio: PortfolioDistribution
    business_criticality: BusinessCriticalityDistribution
    hosting: HostingDistribution
    technology: TechnologyDistribution
    security_access: SecurityAccessDistribution


class DashboardDataQuality(ApiSchema):
    overall_completeness: float | None = None
    matched_mandatory_columns: list[MandatoryColumnMatch] | None = None
    missing_mandatory_columns: list[str] | None = None
    duplicate_application_code_group_count: int | None = None
    duplicate_application_name_group_count: int | None = None
    warning_count: int | None = None


class DashboardSimilaritySummary(ApiSchema):
    similar_pair_count: int | None = None
    possible_duplicate_count: int | None = None
    similar_pair_threshold: float | None = None
    possible_duplicate_threshold: float | None = None
    top_possible_duplicates: list[SimilarPair] = Field(default_factory=list)


class DashboardGeneratedFrom(ApiSchema):
    cmdb_preview_available: bool
    validation_result_available: bool
    similarity_result_available: bool


class DashboardMetricsResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["dashboard_metrics"] = "dashboard_metrics"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    overview: DashboardOverview
    cards: list[DashboardCard] = Field(default_factory=list)
    distributions: DashboardDistributions
    data_quality: DashboardDataQuality
    similarity_summary: DashboardSimilaritySummary
    warnings: list[str] = Field(default_factory=list)
    generated_from: DashboardGeneratedFrom
    summary_endpoint: str
