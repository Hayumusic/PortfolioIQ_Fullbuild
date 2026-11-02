from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext


class UncertainItemsModule:
    name = "uncertain-items"

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Uncertain-items analysis is scaffolded; no classifications were recommended.",
            next_implementation_note=(
                "Add configurable deterministic uncertainty checks, then optional evidence-limited "
                "AI recommendations that require manual verification."
            ),
            result={},
        )
