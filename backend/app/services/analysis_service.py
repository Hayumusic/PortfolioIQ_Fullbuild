from collections.abc import Iterable

from app.core.config import Settings
from app.domain.models import AnalysisInput, AnalysisResult
from app.modules.base import AnalysisContext, AnalysisModule
from app.modules.dashboard_metrics import DashboardMetricsModule
from app.modules.outputs import OutputFamiliesModule, OutputsModule
from app.modules.portfolio_insights import PortfolioInsightsModule
from app.modules.similarity import SimilarityModule
from app.modules.technology_integrations import (
    TechnologyIntegrationsModule,
    TechnologyModule,
)
from app.modules.uncertain_items import UncertainItemsModule
from app.modules.validation import ValidationModule
from app.services.job_service import JobService
from app.services.cmdb_similarity_service import CMDBSimilarityService
from app.services.dashboard_metrics_service import DashboardMetricsService
from app.services.openai_service import OpenAIService
from app.services.output_family_analysis_service import OutputFamilyAnalysisService
from app.services.portfolio_insights_service import PortfolioInsightsService
from app.services.technology_analysis_service import TechnologyAnalysisService
from app.storage.base import StorageProvider


class AnalysisService:
    """Orchestrates independent analysis modules and shared service dependencies."""

    def __init__(
        self,
        job_service: JobService,
        openai_service: OpenAIService,
        storage: StorageProvider,
        settings: Settings,
        similarity_service: CMDBSimilarityService | None = None,
        dashboard_metrics_service: DashboardMetricsService | None = None,
        technology_analysis_service: TechnologyAnalysisService | None = None,
        output_family_analysis_service: OutputFamilyAnalysisService | None = None,
        portfolio_insights_service: PortfolioInsightsService | None = None,
        modules: Iterable[AnalysisModule] | None = None,
    ) -> None:
        self.job_service = job_service
        self.openai_service = openai_service
        self.storage = storage
        self.settings = settings
        self.similarity_service = similarity_service or CMDBSimilarityService(
            storage, job_service
        )
        self.dashboard_metrics_service = (
            dashboard_metrics_service
            or DashboardMetricsService(storage, job_service)
        )
        self.technology_analysis_service = (
            technology_analysis_service
            or TechnologyAnalysisService(storage, job_service)
        )
        self.output_family_analysis_service = output_family_analysis_service
        self.portfolio_insights_service = (
            portfolio_insights_service
            or PortfolioInsightsService(storage, job_service)
        )
        registered_modules = (
            modules
            if modules is not None
            else (
                ValidationModule(),
                SimilarityModule(self.similarity_service),
                DashboardMetricsModule(self.dashboard_metrics_service),
                TechnologyModule(self.technology_analysis_service),
                TechnologyIntegrationsModule(),
                *(
                    (OutputFamiliesModule(self.output_family_analysis_service),)
                    if self.output_family_analysis_service is not None
                    else ()
                ),
                PortfolioInsightsModule(self.portfolio_insights_service),
                OutputsModule(),
                UncertainItemsModule(),
            )
        )
        self._modules: dict[str, AnalysisModule] = {}
        for module in registered_modules:
            if module.name in self._modules:
                raise ValueError(f"Duplicate analysis module name: {module.name}")
            self._modules[module.name] = module

    async def run_module(
        self, module_name: str, job_id: str, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        job = self.job_service.require_job(job_id)
        module = self._modules.get(module_name)
        if module is None:
            raise ValueError(f"Unknown analysis module: {module_name}")
        context = AnalysisContext(
            job=job,
            settings=self.settings,
            storage=self.storage,
            openai_service=self.openai_service,
        )
        return await module.execute(context, analysis_input)
