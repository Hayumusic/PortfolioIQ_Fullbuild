from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import Settings
from app.domain.models import AnalysisInput, AnalysisResult, Job
from app.services.openai_service import OpenAIService
from app.storage.base import StorageProvider


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Job-scoped dependencies available to an analysis module."""

    job: Job
    settings: Settings
    storage: StorageProvider
    openai_service: OpenAIService


@runtime_checkable
class AnalysisModule(Protocol):
    """Contract implemented by deterministic and future AI-assisted modules."""

    name: str

    async def execute(
        self,
        context: AnalysisContext,
        analysis_input: AnalysisInput,
    ) -> AnalysisResult: ...
