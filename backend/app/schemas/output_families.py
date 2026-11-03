from typing import Literal

from pydantic import Field

from app.schemas.common import ApiSchema, ResponseStatus

Confidence = Literal["High", "Medium", "Low", "Insufficient Evidence"]
ClassificationStatus = Literal["Classified", "Multiple Families", "Insufficient Evidence"]


class OutputFamilyAnalysisRequest(ApiSchema):
    family_limit: int = Field(default=50, ge=1, le=500)
    member_limit: int = Field(default=200, ge=1, le=5_000)
    include_unmapped: bool = True
    include_inactive: bool = True


class OutputAssignment(ApiSchema):
    output_family: str
    output_cluster: str
    evidence: list[str] = Field(default_factory=list)


class OutputFamilySummary(ApiSchema):
    total_families_analyzed: int
    total_application_count: int
    classified_application_count: int
    evidence_clustered_application_count: int
    applications_in_multiple_families: int
    insufficient_evidence_application_count: int
    unclassified_application_count: int
    warning_count: int
    source_of_truth_label: str
    reliability_label: str


class OutputFamilyRecord(ApiSchema):
    family_key: str
    family_name: str
    family_description: str | None = None
    member_count: int
    portfolio_count: int = 0
    multiple_family_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class OutputFamilyMember(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None
    family_key: str | None = None
    family_name: str | None = None
    output_cluster: str | None = None
    confidence: Confidence
    classification_status: ClassificationStatus
    fields_used: list[str] = Field(default_factory=list)
    matched_evidence: list[str] = Field(default_factory=list)
    classification_rationale: str
    warnings: list[str] = Field(default_factory=list)


class OutputFamilyMemberFlat(OutputFamilyMember):
    pass


class OutputFamilyDetail(OutputFamilyRecord):
    pass


class OutputFamilyGap(ApiSchema):
    gap_type: str
    severity: Literal["info", "warning", "critical"]
    family_key: str | None = None
    family_name: str | None = None
    application_code: str | None = None
    application_name: str | None = None
    description: str
    recommended_action: str


class OutputFamilyApplication(ApiSchema):
    application_code: str | None = None
    application_name: str
    portfolio: str | None = None
    business_criticality: str | None = None
    assignments: list[OutputAssignment] = Field(default_factory=list)
    output_families: list[str] = Field(default_factory=list)
    output_clusters: list[str] = Field(default_factory=list)
    output_family_count: int
    assigned_output_family: str
    assigned_output_cluster: str
    confidence: Confidence
    classification_status: ClassificationStatus
    fields_used: list[str] = Field(default_factory=list)
    matched_evidence: list[str] = Field(default_factory=list)
    classification_rationale: str
    comment: str = ""
    warnings: list[str] = Field(default_factory=list)


class OutputFamilyAnalysisResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["output_families"] = "output_families"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: OutputFamilySummary
    top_output_families: list[OutputFamilyRecord] = Field(default_factory=list)
    member_sample: list[OutputFamilyMemberFlat] = Field(default_factory=list)
    gap_sample: list[OutputFamilyGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary_endpoint: str
    families_endpoint: str
    members_endpoint: str
    gaps_endpoint: str
    application_matrix_endpoint: str
    families_csv_endpoint: str
    members_csv_endpoint: str
    gaps_csv_endpoint: str
    detail_endpoints: dict[str, str] = Field(default_factory=dict)


class OutputFamilySummaryResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.ANALYZED
    module_name: Literal["output_families"] = "output_families"
    job_id: str
    upload_id: str
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: OutputFamilySummary
    warnings: list[str] = Field(default_factory=list)


class OutputFamiliesResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_family_count: int
    families: list[OutputFamilyRecord] = Field(default_factory=list)


class OutputFamilyDetailResponse(ApiSchema):
    job_id: str
    upload_id: str
    family: OutputFamilyDetail
    members: list[OutputFamilyMember] = Field(default_factory=list)


class OutputFamilyMembersResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_member_count: int
    members: list[OutputFamilyMemberFlat] = Field(default_factory=list)


class OutputFamilyGapsResponse(ApiSchema):
    job_id: str
    upload_id: str
    warning_count: int
    gaps: list[OutputFamilyGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OutputFamilyApplicationMatrixResponse(ApiSchema):
    job_id: str
    upload_id: str
    limit: int
    total_application_count: int
    applications: list[OutputFamilyApplication] = Field(default_factory=list)


class OutputFamilyFilterOptions(ApiSchema):
    portfolios: list[str] = Field(default_factory=list)
    output_families: list[str] = Field(default_factory=list)
    confidences: list[Confidence] = Field(default_factory=list)
    classification_statuses: list[ClassificationStatus] = Field(default_factory=list)


class OutputFamilyAnalysisRow(ApiSchema):
    output_family: str
    application_count: int
    portfolio_count: int
    multiple_family_count: int


class OutputFamilyCoverageRow(ApiSchema):
    portfolio: str
    output_family: str
    application_count: int


class OutputFamilyOverlapRow(ApiSchema):
    output_family: str
    number_of_applications: int
    number_of_portfolios: int
    potential_overlap: bool


class OutputFamilyAnalysisViewResponse(ApiSchema):
    options: OutputFamilyFilterOptions
    filtered_application_count: int
    insufficient_evidence_application_count: int
    multiple_family_application_count: int
    families: list[OutputFamilyAnalysisRow] = Field(default_factory=list)
    coverage: list[OutputFamilyCoverageRow] = Field(default_factory=list)
    potential_overlaps: list[OutputFamilyOverlapRow] = Field(default_factory=list)


class ApplicationOutputMappingRow(OutputFamilyApplication):
    pass


class ApplicationOutputMappingResponse(ApiSchema):
    options: OutputFamilyFilterOptions
    display_size: Literal["50", "100", "200", "all"]
    total_application_count: int
    returned_application_count: int
    insufficient_evidence_application_count: int
    multiple_family_application_count: int
    applications: list[ApplicationOutputMappingRow] = Field(default_factory=list)
