from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.domain.models import UploadKind
from app.schemas.common import ApiSchema, ModuleResponse, ResponseStatus


class JobResponse(ApiSchema):
    status: ResponseStatus
    job_id: str
    created_at: datetime
    uploads: dict[str, list[str]] = Field(default_factory=dict)
    message: str


class UploadedFileMetadata(ApiSchema):
    upload_id: str
    filename: str
    stored_filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    uploaded_at: datetime | None = None
    processed: bool = False
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = Field(default_factory=list)
    page_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class UploadResponse(ModuleResponse):
    upload_kind: UploadKind
    file_names: list[str]
    upload_id: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    validation_status: str | None = None
    files: list[UploadedFileMetadata] = Field(default_factory=list)


class MandatoryFieldsRequest(ApiSchema):
    mandatory_fields: list[str] = Field(min_length=1)

    @field_validator("mandatory_fields")
    @classmethod
    def normalize_fields(cls, fields: list[str]) -> list[str]:
        normalized = [field.strip() for field in fields if field.strip()]
        if not normalized:
            raise ValueError("At least one non-empty mandatory field is required")
        return normalized


class MandatoryFieldsResponse(ModuleResponse):
    mandatory_fields: list[str]


class MandatoryFieldsConfigUploadResponse(ModuleResponse):
    upload_id: str
    file: UploadedFileMetadata
    configured_mandatory_fields: list[str]
    row_count: int
    warnings: list[str] = Field(default_factory=list)
    usable: bool


class MandatoryFieldsJobConfigResponse(ApiSchema):
    job_id: str
    upload_id: str | None
    mandatory_fields: list[str]
    row_count: int
    warnings: list[str] = Field(default_factory=list)
    usable: bool


class OutputFamilyDefinition(ApiSchema):
    key: str | None = None
    name: str
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None
    members: list[dict[str, str | None]] = Field(default_factory=list)


class OutputFamilyConfigUploadResponse(ModuleResponse):
    upload_id: str
    file: UploadedFileMetadata
    family_count: int
    families: list[OutputFamilyDefinition]
    row_count: int
    warnings: list[str] = Field(default_factory=list)
    usable: bool


class OutputFamiliesJobConfigResponse(ApiSchema):
    job_id: str
    upload_id: str | None
    family_count: int
    families: list[OutputFamilyDefinition]
    row_count: int
    warnings: list[str] = Field(default_factory=list)
    usable: bool


class SupportingUploadResponse(ModuleResponse):
    upload_id: str
    upload_kind: UploadKind
    files: list[UploadedFileMetadata]
    file_count: int
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    processed: bool
    stored_for_future_analysis: bool


class UploadSourceStatus(ApiSchema):
    required: bool
    uploaded: bool
    processed: bool
    upload_count: int
    latest_upload_id: str | None = None
    latest_filename: str | None = None
    accepted_file_types: list[str]
    warnings: list[str] = Field(default_factory=list)


class UploadSources(ApiSchema):
    cmdb: UploadSourceStatus
    mandatory_fields_config: UploadSourceStatus
    output_family_config: UploadSourceStatus
    confluence: UploadSourceStatus
    team_validation: UploadSourceStatus
    cloudwatch: UploadSourceStatus


class UploadStatusResponse(ApiSchema):
    job_id: str
    sources: UploadSources
    cmdb_ready: bool
    mandatory_fields_config_ready: bool
    output_family_config_ready: bool
    optional_inputs_available: bool
    can_run_validation: bool
    can_run_outputs_analysis: bool
    missing_required_inputs: list[
        Literal["cmdb", "mandatory_fields_config", "output_family_config"]
    ]
    warnings: list[str] = Field(default_factory=list)
