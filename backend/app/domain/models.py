from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class UploadKind(StrEnum):
    CMDB = "cmdb"
    MANDATORY_FIELDS_CONFIG = "mandatory_fields_config"
    OUTPUT_FAMILY_CONFIG = "output_family_config"
    CONFLUENCE = "confluence"
    TEAM_VALIDATION = "team_validation"
    # Retained for compatibility with the original optional-upload route.
    VALIDATION = "validation"
    CLOUDWATCH = "cloudwatch"


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    created_at: datetime
    uploads: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UploadBatchResult:
    job_id: str
    kind: UploadKind
    file_names: list[str]


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    force: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    module_name: str
    job_id: str
    message: str
    next_implementation_note: str
    result: dict[str, Any] = field(default_factory=dict)
