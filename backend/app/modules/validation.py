from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext


class ValidationModule:
    name = "validation"

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Validation analysis is scaffolded; no uploaded records were analyzed.",
            next_implementation_note=(
                "Add deterministic Excel parsing, mandatory-field checks, completeness, "
                "duplicate detection, and source/reliability labels."
            ),
            result={},
        )
