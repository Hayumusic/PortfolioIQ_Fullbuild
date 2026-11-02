from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext
from app.services.technology_analysis_service import TechnologyAnalysisService


class TechnologyModule:
    name = "technology"

    def __init__(self, service: TechnologyAnalysisService) -> None:
        self.service = service

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        result = self.service.run_analysis(
            context.job.job_id,
            **analysis_input.options,
        )
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Deterministic technology and integration analysis completed.",
            next_implementation_note=(
                "Review technology clusters, explicit integration maps, and potential obsolete technology indicators."
            ),
            result=result,
        )


class TechnologyIntegrationsModule:
    name = "technology-integrations"

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Technology and integration analysis is scaffolded; no findings were generated.",
            next_implementation_note=(
                "Add independent extraction, integration graph, technology clustering, obsolete "
                "technology rules, and risk scoring components."
            ),
            result={},
        )
