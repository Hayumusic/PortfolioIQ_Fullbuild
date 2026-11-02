from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext
from app.services.portfolio_insights_service import PortfolioInsightsService


class PortfolioInsightsModule:
    name = "portfolio_insights"

    def __init__(self, service: PortfolioInsightsService) -> None:
        self.service = service

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        result = self.service.run_analysis(
            context.job.job_id, **analysis_input.options
        )
        return AnalysisResult(
            module_name=self.name,
            job_id=context.job.job_id,
            message="Deterministic cross-module portfolio insights completed.",
            next_implementation_note=(
                "Review the executive summary, scorecards, risks, and action items."
            ),
            result=result,
        )
