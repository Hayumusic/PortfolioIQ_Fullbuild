from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext
from app.services.output_family_analysis_service import OutputFamilyAnalysisService


class OutputFamiliesModule:
    name = "output_families"

    def __init__(self, service: OutputFamilyAnalysisService) -> None:
        self.service = service

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        result = await self.service.run_analysis(
            context.job.job_id, **analysis_input.options
        )
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Deterministic output classification completed.",
            next_implementation_note=(
                "Review taxonomy matches, evidence fields, confidence, and rationale."
            ),
            result=result,
        )


class OutputsModule:
    name = "outputs"

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Application outputs analysis is scaffolded; no outputs were classified.",
            next_implementation_note=(
                "Add configurable output-family keyword matching, matrices, and evidence-backed "
                "redundancy alerts."
            ),
            result={},
        )
