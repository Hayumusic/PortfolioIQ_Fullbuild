from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext
from app.services.cmdb_similarity_service import CMDBSimilarityService


class SimilarityModule:
    name = "similarity"

    def __init__(self, service: CMDBSimilarityService) -> None:
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
            message="Deterministic CMDB similarity analysis completed.",
            next_implementation_note="Review paginated pairs and per-application matches.",
            result=result,
        )
