from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ResponseStatus(StrEnum):
    HEALTHY = "healthy"
    CREATED = "created"
    UPLOADED = "uploaded"
    READY = "ready"
    VALIDATED = "validated"
    ANALYZED = "analyzed"
    PLACEHOLDER = "placeholder"
    DELETED = "deleted"


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiSchema):
    status: ResponseStatus
    service: str
    environment: str


class ModuleResponse(ApiSchema):
    status: ResponseStatus
    module_name: str
    job_id: str | None = None
    message: str
    next_implementation_note: str
