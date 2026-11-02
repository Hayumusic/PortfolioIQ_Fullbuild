from typing import Any

from pydantic import Field

from app.schemas.common import ApiSchema, ModuleResponse


class AnalysisRequest(ApiSchema):
    force: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(ModuleResponse):
    result: dict[str, Any] = Field(default_factory=dict)
