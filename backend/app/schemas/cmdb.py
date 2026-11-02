from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiSchema, ResponseStatus


class MandatoryColumnMatch(ApiSchema):
    configured_field: str
    cmdb_column: str


class MandatoryFieldMapping(ApiSchema):
    configured_field: str
    cmdb_column: str | None
    matched: bool
    match_type: str


class TeamValidationSummary(ApiSchema):
    team_validation_available: bool
    upload_id: str | None
    row_count: int
    column_count: int
    columns: list[str]
    application_code_column: str | None
    rows_with_application_code: int
    rows_missing_application_code: int
    unmatched_team_validation_records: int
    cmdb_applications_missing_team_validation_record: int
    yes_no_column: str | None
    invalid_yes_no_value_count: int


class OptionalInputSummary(ApiSchema):
    confluence_available: bool
    confluence_file_count: int
    team_validation_available: bool
    team_validation_upload_id: str | None
    cloudwatch_available: bool
    cloudwatch_upload_id: str | None
    source_of_truth_inputs_used: list[str]


class DuplicateValue(ApiSchema):
    value: str
    row_numbers: list[int]


class CMDBValidationSummary(ApiSchema):
    total_row_count: int
    total_column_count: int
    overall_completeness: float
    matched_mandatory_columns: list[MandatoryColumnMatch]
    missing_mandatory_columns: list[str]
    mandatory_field_mappings: list[MandatoryFieldMapping]
    mandatory_fields_config_source: Literal[
        "job_upload", "global_config", "default_or_missing"
    ]
    mandatory_fields_config_upload_id: str | None
    application_code_column: str | None
    application_id_column: str | None
    duplicate_application_codes: list[DuplicateValue]
    duplicate_application_ids: list[DuplicateValue]
    duplicate_application_names: list[DuplicateValue]
    evidence_type: Literal["Direct CMDB Evidence"]
    source_of_truth_label: Literal[
        "Source of Truth 1", "Source of Truth 2", "Source of Truth 3"
    ]
    reliability_label: Literal["Average", "High"]
    reliability_reason: str
    reliability_note: str
    team_validation_summary: TeamValidationSummary
    optional_input_summary: OptionalInputSummary
    missing_data_warnings: list[str]


class CMDBValidationSummaryMetrics(ApiSchema):
    total_row_count: int
    total_column_count: int
    overall_completeness: float
    matched_mandatory_columns: list[MandatoryColumnMatch]
    missing_mandatory_columns: list[str]
    mandatory_field_mappings: list[MandatoryFieldMapping]
    mandatory_fields_config_source: Literal[
        "job_upload", "global_config", "default_or_missing"
    ]
    mandatory_fields_config_upload_id: str | None
    application_code_column: str | None
    application_id_column: str | None
    duplicate_application_code_group_count: int
    duplicate_application_id_group_count: int
    duplicate_application_name_group_count: int
    warning_count: int
    missing_data_warnings: list[str]
    source_of_truth_label: Literal[
        "Source of Truth 1", "Source of Truth 2", "Source of Truth 3"
    ] | None = None
    reliability_label: Literal["Average", "High"] | None = None
    reliability_reason: str | None = None
    team_validation_summary: TeamValidationSummary | None = None
    optional_input_summary: OptionalInputSummary | None = None


class ApplicationValidationResult(ApiSchema):
    internal_row_number: int
    application_key: str
    application_code: str | None = None
    application_name: str
    completeness_percentage: float
    missing_mandatory_fields: list[str]
    evidence_type: Literal["Direct CMDB Evidence"]
    source_of_truth_label: Literal[
        "Source of Truth 1", "Source of Truth 2", "Source of Truth 3"
    ]
    reliability_label: Literal["Average", "High"]
    missing_data_warnings: list[str]
    source_data: dict[str, Any]


class CMDBValidationResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.VALIDATED
    module_name: Literal["validation"] = "validation"
    job_id: str
    upload_id: str
    validation_status: Literal["validated", "completed_with_warnings"]
    summary: CMDBValidationSummary
    applications: list[ApplicationValidationResult] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class CMDBValidationOverviewResponse(ApiSchema):
    status: ResponseStatus = ResponseStatus.VALIDATED
    module_name: Literal["validation"] = "validation"
    job_id: str
    upload_id: str
    validation_status: Literal["validated", "completed_with_warnings"]
    analysis_status: Literal["completed", "completed_with_warnings"]
    summary: CMDBValidationSummaryMetrics
    warnings: list[str] = Field(default_factory=list)
    details_endpoint: str
    duplicates_endpoint: str
    completeness_csv_endpoint: str
    detail_endpoints: dict[str, str] = Field(default_factory=dict)


class CMDBValidationDetailsResponse(ApiSchema):
    job_id: str
    upload_id: str
    page: int
    page_size: int
    total_records: int
    total_pages: int
    records: list[ApplicationValidationResult]


class CMDBValidationDuplicatesResponse(ApiSchema):
    job_id: str
    upload_id: str
    duplicate_application_code_group_count: int
    duplicate_application_id_group_count: int
    duplicate_application_name_group_count: int
    duplicate_application_codes: list[DuplicateValue]
    duplicate_application_ids: list[DuplicateValue]
    duplicate_application_names: list[DuplicateValue]


class CMDBColumnsResponse(ApiSchema):
    job_id: str
    upload_id: str
    total_column_count: int
    columns: list[str]
    application_code_column: str | None
    application_id_column: str | None
    application_name_column: str | None


class CMDBApplication(ApiSchema):
    internal_row_number: int
    application_code: str | None = None
    application_name: str | None = None


class CMDBApplicationsResponse(ApiSchema):
    job_id: str
    upload_id: str
    total_records: int
    applications: list[CMDBApplication] = Field(default_factory=list)
