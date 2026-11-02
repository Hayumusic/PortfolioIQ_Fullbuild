from typing import Literal

from pydantic import Field

from app.schemas.common import ApiSchema, ResponseStatus


TechnologyType = Literal[
    "technology_stack",
    "application_technology",
    "platform",
    "hosting_provider",
    "hosting_type",
    "database_technology",
]


class TechnologyAnalysisRequest(ApiSchema):
    top_n: int = Field(default=10, ge=1, le=100)
    cluster_limit: int = Field(default=50, ge=1, le=500)
    integration_limit: int = Field(default=100, ge=1, le=1_000)
    include_obsolete: bool = True


class TechnologyApplication(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None
    business_criticality: str | None = None


class TechnologyConcernEvidence(ApiSchema):
    application_code: str | None = None
    application_name: str
    source_field: str
    evidence_value: str
    reason: str


class TechnologyCluster(ApiSchema):
    cluster_key: str
    label: str
    technology_type: TechnologyType
    application_count: int
    risky_application_count: int = 0
    lifecycle_status: str = "Not Available"
    shortcomings: list[str] = Field(default_factory=list)
    concern_evidence: list[TechnologyConcernEvidence] = Field(default_factory=list)
    applications: list[TechnologyApplication] = Field(default_factory=list)
    cluster_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class IntegrationRecord(ApiSchema):
    source_application_code: str | None = None
    source_application_name: str
    target_application_code: str | None = None
    target_application_name: str | None = None
    integration_type: str
    evidence_field: str
    evidence_value: str
    confidence: Literal["low", "medium", "high"]
    warning: str | None = None
    direction: Literal["incoming", "outgoing", "unknown", "directed"] = "unknown"


class ObsoleteIndicator(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None
    business_criticality: str | None = None
    field: str
    value: str
    indicator: str = ""
    reason: str
    severity: Literal["info", "warning", "critical"]


class TechnologySummary(ApiSchema):
    total_applications_analyzed: int
    technology_cluster_count: int
    integration_count: int
    explicit_integration_data_available: bool
    obsolete_indicator_count: int
    source_of_truth_label: str
    reliability_label: str
    warning_count: int


class IntegrationSummary(ApiSchema):
    total_integration_count: int
    integration_data_available: bool
    integrations: list[IntegrationRecord] = Field(default_factory=list)


class ObsoleteSummary(ApiSchema):
    obsolete_indicator_count: int
    indicators: list[ObsoleteIndicator] = Field(default_factory=list)


class TechnologyAnalysisResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["technology"] = "technology"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: TechnologySummary
    top_technology_clusters: list[TechnologyCluster] = Field(default_factory=list)
    integration_summary: IntegrationSummary
    obsolete_summary: ObsoleteSummary
    warnings: list[str] = Field(default_factory=list)
    summary_endpoint: str
    clusters_endpoint: str
    integrations_endpoint: str
    application_map_endpoint: str
    portfolio_map_endpoint: str
    obsolete_endpoint: str
    clusters_csv_endpoint: str
    integrations_csv_endpoint: str
    detail_endpoints: dict[str, str] = Field(default_factory=dict)


class TechnologySummaryResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["technology"] = "technology"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: TechnologySummary
    warnings: list[str] = Field(default_factory=list)


class TechnologyClustersResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    portfolio: str | None = None
    scope_application_count: int
    total_cluster_count: int
    clusters: list[TechnologyCluster] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TechnologyIntegrationsResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_integration_count: int
    integration_data_available: bool
    integrations: list[IntegrationRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplicationMapNode(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None
    technology_summary: str | None = None


class ApplicationMapEdge(ApiSchema):
    source_application_code: str | None = None
    target_application_code: str | None = None
    integration_type: str
    confidence: Literal["low", "medium", "high"]
    evidence: str


class ApplicationMapResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    nodes: list[ApplicationMapNode] = Field(default_factory=list)
    edges: list[ApplicationMapEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PortfolioMapNode(ApiSchema):
    portfolio: str
    application_count: int


class PortfolioMapEdge(ApiSchema):
    source_portfolio: str
    target_portfolio: str
    integration_count: int
    confidence: Literal["low", "medium", "high"]


class PortfolioMapResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    nodes: list[PortfolioMapNode] = Field(default_factory=list)
    edges: list[PortfolioMapEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ObsoleteTechnologyResponse(ApiSchema):
    job_id: str
    upload_id: str
    obsolete_indicator_count: int
    page: int = 1
    page_size: int | Literal["all"] = 25
    indicators: list[ObsoleteIndicator] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TechnologyDimensionOption(ApiSchema):
    key: TechnologyType
    label: str


class TechnologyOptionApplication(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None


class TechnologyOptionsResponse(ApiSchema):
    dimensions: list[TechnologyDimensionOption] = Field(default_factory=list)
    portfolios: list[str] = Field(default_factory=list)
    business_criticalities: list[str] = Field(default_factory=list)
    applications: list[TechnologyOptionApplication] = Field(default_factory=list)
    integration_types: list[str] = Field(default_factory=list)
    confidence_options: list[Literal["high", "medium", "low"]] = Field(default_factory=list)
    indicator_options: list[str] = Field(default_factory=list)


class TechnologyGrouping(ApiSchema):
    label: str
    application_count: int


class TechnologyPortfolioGrouping(ApiSchema):
    portfolio: str
    technology_value: str
    application_count: int


class TechnologyLandscapeApplication(TechnologyApplication):
    technology_dimension: str
    technology_value: str


class TechnologyLandscapeResponse(ApiSchema):
    dimension: TechnologyType
    dimension_label: str
    groupings: list[TechnologyGrouping] = Field(default_factory=list)
    portfolio_groupings: list[TechnologyPortfolioGrouping] = Field(default_factory=list)
    selected_technology_value: str | None = None
    total_application_count: int
    page: int
    page_size: int | Literal["all"]
    applications: list[TechnologyLandscapeApplication] = Field(default_factory=list)


class IntegrationNeighborhoodNode(ApiSchema):
    application_code: str
    application_name: str
    portfolio: str | None = None
    business_criticality: str | None = None
    anchor: bool = False


class IntegrationNeighborhoodEdge(ApiSchema):
    source_application_code: str
    target_application_code: str
    integration_type: str
    confidence: Literal["low", "medium", "high"]
    direction: Literal["incoming", "outgoing", "unknown", "directed"]
    evidence_field: str


class PortfolioDependency(ApiSchema):
    source_portfolio: str
    target_portfolio: str
    integration_count: int


class IntegrationHub(ApiSchema):
    application_name: str
    application_code: str | None = None
    portfolio: str | None = None
    business_criticality: str | None = None
    total_connections: int
    incoming_connections: int
    outgoing_related_connections: int


class IntegrationNeighborhoodResponse(ApiSchema):
    selected_application: IntegrationNeighborhoodNode
    total_integration_count: int
    page: int
    page_size: int | Literal["all"]
    integrations: list[IntegrationRecord] = Field(default_factory=list)
    nodes: list[IntegrationNeighborhoodNode] = Field(default_factory=list)
    edges: list[IntegrationNeighborhoodEdge] = Field(default_factory=list)
    graph_truncated: bool
    graph_edge_limit: int
    portfolio_dependencies: list[PortfolioDependency] = Field(default_factory=list)
    integration_hubs: list[IntegrationHub] = Field(default_factory=list)


class TechnologyInventoryApplication(ApiSchema):
    application_name: str
    application_code: str | None = None
    portfolio: str | None = None
    business_criticality: str | None = None
    hosting_type: str | None = None
    hosting_provider: str | None = None
    technology_stack: str | None = None
    database_technology: str | None = None
    integration_count: int
    incoming_integration_count: int
    outgoing_related_integration_count: int
    integration_types: list[str] = Field(default_factory=list)
    potential_legacy_indicator: bool


class TechnologyInventoryResponse(ApiSchema):
    total_application_count: int
    filtered_application_count: int
    page: int
    page_size: int | Literal["all"]
    applications: list[TechnologyInventoryApplication] = Field(default_factory=list)
