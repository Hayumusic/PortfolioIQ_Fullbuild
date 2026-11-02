from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext
from app.services.dashboard_metrics_service import DashboardMetricsService


class DashboardMetricsModule:
    name = "dashboard_metrics"

    def __init__(self, service: DashboardMetricsService) -> None:
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
            message="Deterministic dashboard metrics generation completed.",
            next_implementation_note="Render the compact cards and distributions in the dashboard UI.",
            result=result,
        )
