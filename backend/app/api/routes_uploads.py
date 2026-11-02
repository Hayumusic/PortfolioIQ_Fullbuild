from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.api.dependencies import (
    CMDBServiceDependency,
    FileServiceDependency,
    JobServiceDependency,
    MandatoryFieldConfigServiceDependency,
    UploadConfigServiceDependency,
)
from app.domain.models import Job, UploadKind
from app.schemas.common import ResponseStatus
from app.schemas.cmdb import CMDBApplicationsResponse, CMDBColumnsResponse
from app.schemas.uploads import (
    JobResponse,
    MandatoryFieldsRequest,
    MandatoryFieldsResponse,
    MandatoryFieldsConfigUploadResponse,
    MandatoryFieldsJobConfigResponse,
    OutputFamiliesJobConfigResponse,
    OutputFamilyConfigUploadResponse,
    SupportingUploadResponse,
    UploadStatusResponse,
    UploadResponse,
)

router = APIRouter(tags=["jobs and uploads"])


def _job_response(
    job: Job, status_value: ResponseStatus, message: str
) -> JobResponse:
    return JobResponse(
        status=status_value,
        job_id=job.job_id,
        created_at=job.created_at,
        uploads=job.uploads,
        message=message,
    )


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(job_service: JobServiceDependency) -> JobResponse:
    return _job_response(
        job_service.create_job(), ResponseStatus.CREATED, "Job session created."
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, job_service: JobServiceDependency) -> JobResponse:
    return _job_response(
        job_service.get_job(job_id), ResponseStatus.READY, "Job session is available."
    )


@router.delete("/jobs/{job_id}", response_model=JobResponse)
def delete_job(job_id: str, job_service: JobServiceDependency) -> JobResponse:
    return _job_response(
        job_service.delete_job(job_id), ResponseStatus.DELETED, "Job files were deleted."
    )


def _save_files(
    file_service: FileServiceDependency,
    job_id: str,
    kind: UploadKind,
    files: list[UploadFile],
) -> UploadResponse:
    batch = file_service.save_upload_batch(
        job_id,
        kind,
        [(file.filename, file.file) for file in files],
    )
    return UploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name="uploads",
        job_id=job_id,
        message=f"{len(batch.file_names)} {kind.value} file(s) stored for this job.",
        next_implementation_note=(
            "Add source-specific parsing and validation; the scaffold currently preserves "
            "the uploaded file without analyzing its contents."
        ),
        upload_kind=kind,
        file_names=batch.file_names,
    )


@router.post("/jobs/{job_id}/upload/cmdb", response_model=UploadResponse)
def upload_cmdb(
    job_id: str,
    cmdb_service: CMDBServiceDependency,
    file: Annotated[UploadFile, File(description="Required CMDB .xlsx or .xls file")],
) -> UploadResponse:
    result = cmdb_service.upload(job_id, file.filename, file.file)
    return UploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name="uploads",
        job_id=job_id,
        message="CMDB workbook was parsed and stored for this job.",
        next_implementation_note=(
            "Configure mandatory fields, then run the CMDB validation endpoint."
        ),
        upload_kind=UploadKind.CMDB,
        file_names=result["file_names"],
        upload_id=result["upload_id"],
        row_count=result["row_count"],
        column_count=result["column_count"],
        validation_status="not_run",
        files=[result["file"]],
    )


@router.post(
    "/jobs/{job_id}/upload/mandatory-fields-config",
    response_model=MandatoryFieldsConfigUploadResponse,
)
def upload_mandatory_fields_config(
    job_id: str,
    upload_service: UploadConfigServiceDependency,
    file: Annotated[
        UploadFile, File(description="Mandatory-fields .xlsx, .xls, or .csv file")
    ],
) -> MandatoryFieldsConfigUploadResponse:
    result = upload_service.upload_mandatory_fields_config(
        job_id, file.filename, file.file
    )
    return MandatoryFieldsConfigUploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name="mandatory-fields-configuration",
        job_id=job_id,
        message="Mandatory-fields configuration was parsed and stored for this job.",
        next_implementation_note="The uploaded configuration is ready for CMDB validation.",
        **{key: value for key, value in result.items() if key != "job_id"},
    )


@router.post(
    "/jobs/{job_id}/upload/output-family-config",
    response_model=OutputFamilyConfigUploadResponse,
)
def upload_output_family_config(
    job_id: str,
    upload_service: UploadConfigServiceDependency,
    file: Annotated[
        UploadFile, File(description="Output-family .xlsx, .xls, or .csv file")
    ],
) -> OutputFamilyConfigUploadResponse:
    result = upload_service.upload_output_family_config(
        job_id, file.filename, file.file
    )
    return OutputFamilyConfigUploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name="output-family-configuration",
        job_id=job_id,
        message="Output-family configuration was parsed and stored for this job.",
        next_implementation_note=(
            "Upload a CMDB preview, then run deterministic output-family analysis."
        ),
        **{key: value for key, value in result.items() if key != "job_id"},
    )


@router.get("/jobs/{job_id}/cmdb/columns", response_model=CMDBColumnsResponse)
def get_cmdb_columns(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> CMDBColumnsResponse:
    return CMDBColumnsResponse.model_validate(cmdb_service.get_columns(job_id))


@router.get(
    "/jobs/{job_id}/cmdb/applications", response_model=CMDBApplicationsResponse
)
def get_cmdb_applications(
    job_id: str, cmdb_service: CMDBServiceDependency
) -> CMDBApplicationsResponse:
    return CMDBApplicationsResponse.model_validate(
        cmdb_service.get_applications(job_id)
    )


@router.post(
    "/jobs/{job_id}/upload/confluence", response_model=SupportingUploadResponse
)
def upload_confluence(
    job_id: str,
    upload_service: UploadConfigServiceDependency,
    files: Annotated[list[UploadFile], File(description="One or more optional PDF exports")],
) -> SupportingUploadResponse:
    result = upload_service.upload_confluence(
        job_id, [(file.filename, file.file) for file in files]
    )
    return SupportingUploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name="confluence-upload",
        job_id=job_id,
        message="Confluence PDF export(s) stored for future analysis.",
        next_implementation_note="Deep PDF evidence extraction is outside Phase A.",
        **{key: value for key, value in result.items() if key != "job_id"},
    )


@router.post(
    "/jobs/{job_id}/upload/team-validation",
    response_model=SupportingUploadResponse,
)
def upload_team_validation(
    job_id: str,
    upload_service: UploadConfigServiceDependency,
    file: Annotated[
        UploadFile, File(description="Optional team-validation .xlsx, .xls, or .csv file")
    ],
) -> SupportingUploadResponse:
    result = upload_service.upload_supporting_table(
        job_id, UploadKind.TEAM_VALIDATION, file.filename, file.file
    )
    return _supporting_response(result, "team-validation-upload")


@router.post("/jobs/{job_id}/upload/validation", response_model=UploadResponse)
def upload_validation(
    job_id: str,
    file_service: FileServiceDependency,
    file: Annotated[UploadFile, File(description="Optional team validation workbook")],
) -> UploadResponse:
    return _save_files(file_service, job_id, UploadKind.VALIDATION, [file])


@router.post(
    "/jobs/{job_id}/upload/cloudwatch", response_model=SupportingUploadResponse
)
def upload_cloudwatch(
    job_id: str,
    upload_service: UploadConfigServiceDependency,
    file: Annotated[
        UploadFile, File(description="Optional CloudWatch .xlsx, .xls, or .csv file")
    ],
) -> SupportingUploadResponse:
    result = upload_service.upload_supporting_table(
        job_id, UploadKind.CLOUDWATCH, file.filename, file.file
    )
    return _supporting_response(result, "cloudwatch-upload")


def _supporting_response(
    result: dict[str, object], module_name: str
) -> SupportingUploadResponse:
    return SupportingUploadResponse(
        status=ResponseStatus.UPLOADED,
        module_name=module_name,
        job_id=str(result["job_id"]),
        message=f"{str(result['upload_kind']).replace('_', ' ').title()} file stored for future enhancement.",
        next_implementation_note="Only schema-light metadata and a bounded preview are parsed in Phase A.",
        **{key: value for key, value in result.items() if key != "job_id"},
    )


@router.get("/jobs/{job_id}/uploads/status", response_model=UploadStatusResponse)
def get_upload_status(
    job_id: str, upload_service: UploadConfigServiceDependency
) -> UploadStatusResponse:
    return UploadStatusResponse.model_validate(
        upload_service.get_upload_status(job_id)
    )


@router.get(
    "/jobs/{job_id}/config/mandatory-fields",
    response_model=MandatoryFieldsJobConfigResponse,
)
def get_job_mandatory_fields(
    job_id: str, upload_service: UploadConfigServiceDependency
) -> MandatoryFieldsJobConfigResponse:
    return MandatoryFieldsJobConfigResponse(
        job_id=job_id, **upload_service.get_mandatory_fields_config(job_id)
    )


@router.get(
    "/jobs/{job_id}/config/output-families",
    response_model=OutputFamiliesJobConfigResponse,
)
def get_job_output_families(
    job_id: str, upload_service: UploadConfigServiceDependency
) -> OutputFamiliesJobConfigResponse:
    return OutputFamiliesJobConfigResponse(
        job_id=job_id, **upload_service.get_output_families_config(job_id)
    )


@router.put(
    "/config/cmdb-mandatory-fields",
    response_model=MandatoryFieldsResponse,
)
def configure_mandatory_fields(
    payload: MandatoryFieldsRequest,
    config_service: MandatoryFieldConfigServiceDependency,
) -> MandatoryFieldsResponse:
    fields = config_service.set_fields(payload.mandatory_fields)
    return MandatoryFieldsResponse(
        status=ResponseStatus.READY,
        module_name="cmdb-mandatory-field-configuration",
        message="Mandatory-field configuration was stored.",
        next_implementation_note=(
            "Add authentication/authorization and configuration versioning before exposing "
            "this admin operation in production."
        ),
        mandatory_fields=fields,
    )


@router.get(
    "/config/cmdb-mandatory-fields",
    response_model=MandatoryFieldsResponse,
)
def get_mandatory_fields(
    config_service: MandatoryFieldConfigServiceDependency,
) -> MandatoryFieldsResponse:
    fields = config_service.get_fields(required=False)
    return MandatoryFieldsResponse(
        status=ResponseStatus.READY,
        module_name="cmdb-mandatory-field-configuration",
        message=(
            "Mandatory-field configuration is available."
            if fields
            else "Mandatory fields have not been configured."
        ),
        next_implementation_note=(
            "Configure at least one field before running CMDB validation."
        ),
        mandatory_fields=fields,
    )
